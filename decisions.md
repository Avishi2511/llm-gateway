# Decision Log

Running record of design decisions for SecureLLM Gateway: what was chosen, why, and the alternatives, so changes can be made later with context.
Source requirements: `product-spec-mvp.md`. Build plan: `plan.md`.

Status values: **Decided**, **Open** (needs an answer), **Default** (chosen by Claude, easy to change).

---

## D1. Real LLM provider: **Open**
- **Context:** The spec requires one real provider adapter plus a mock.
- **Options:** Anthropic (Claude), OpenAI, Google Gemini.
- **Decision:** Pending user choice.
- **Impact if changed later:** Only `providers/<vendor>.py`, the env var name, and token-usage field mapping change. The provider interface isolates the rest of the code.

## D2. Database: SQLite via SQLAlchemy: **Decided**
- **Why:** Fastest to finish, zero setup, enough for usage history.
- **Alternatives:** PostgreSQL (shows relational skill, needs a server/Docker).
- **Changing later:** Swap the connection URL in settings. SQLAlchemy keeps the models portable.

## D3. Prompt-injection match behaviour: always **block**: **Default**
- **Why:** The spec says "high-confidence" patterns only, so a match should be rejected rather than silently altered.
- **Alternatives:** Per-pattern action (`block`/`allow`/log-only), or log-only mode.
- **Changing later:** Add an `action` field to the pattern config in `guardrails/input.py`.

## D4. PII redaction is a global on/off setting: **Decided**
- **Behaviour:** On → replace email/phone with `[REDACTED_EMAIL]` / `[REDACTED_PHONE]` before the provider call. Off → detection only, recorded as metadata; the content is passed through unchanged.
- **Alternatives:** Per-request override (rejected: clients shouldn't weaken server policy); per-category toggles (possible later).

## D5. Multiple gateway API keys via env var: **Decided**
- **Behaviour:** `GATEWAY_API_KEYS` holds a comma-separated list. Each key gets its own rate limit and usage attribution. Keys are identified in logs/DB by a short non-reversible id, never the raw key.
- **Alternatives:** Single key (simpler, but rate limits/usage per key are meaningless); DB-backed keys with hashing and revocation (spec stretch goal).

## D6. Response shape: flat, per spec: **Decided**
- **Shape:** `request_id`, `model`, assistant message, `usage`, `finish_reason`.
- **Alternatives:** OpenAI-compatible `choices[]` shape, which would let existing OpenAI SDK clients work unmodified. Cost: more schema work, and it hides the gateway's own fields.
- **Changing later:** Contained in `schemas.py` and the response-building step.

## D7. No Docker for now: **Decided**
- **Why:** Not needed for the MVP; spec lists it as optional polish.
- **Changing later:** Add a `Dockerfile` and `docker-compose.yml` in Phase 5.

## D8. Package management: pip + venv + `requirements.txt`: **Default**
- **Why:** No extra tool to install on Windows; every reviewer can run it.
- **Alternatives:** `uv` (faster, lockfile), Poetry. Migrating means generating a `pyproject.toml`.

## D9. Orchestration separate from HTTP layer: **Default**
- **Why:** Spec requires orchestration testable without starting a server. A `gateway/service.py` takes its dependencies (provider, guardrails, repo, limiter) as arguments.
- **Alternatives:** Logic inside route handlers (simpler, but harder to unit-test and to prove "provider not called").

## D10. Model aliases live in settings, no `model_configs` table: **Default**
- **Why:** The spec says one alias is enough and config can live in validated settings. A table adds a migration surface with no benefit yet.
- **Alternatives:** DB table plus admin API (stretch).

## D11. Usage logging records every request, including blocked/failed: **Default**
- **Why:** Blocks and errors are exactly what a maintainer wants to inspect. No prompt or completion text is stored.
- **Alternatives:** Log only successful calls.

---

*Add new entries below as decisions are made. Keep the format: context, decision, why, alternatives, how to change.*

## D12. Unsupported fields are accepted by the schema, then rejected explicitly: **Default** (Phase 1)
- **Why:** `stream`, `tools`, `functions` and list-style (multimodal) message content are declared in the schema so they produce `UNSUPPORTED_FEATURE` (400) rather than a generic validation error. Truly unknown fields are rejected with `INVALID_REQUEST` (422) via `extra="forbid"`, so typos are not silently dropped. `stream: false` is accepted.
- **Alternatives:** Reject all of them as generic validation errors (less helpful to clients).

## D13. Validation errors list field paths only: **Default** (Phase 1)
- **Why:** The message names the offending fields (e.g. `messages.0.role`) but never echoes submitted values, so sensitive content cannot leak through errors. Tested.
- **Alternative:** Fixed message with no field names (safer, less useful).

## D14. Mock `timeout` behaviour raises immediately: **Default** (Phase 1)
- **Why:** Keeps tests fast. The real wall-clock timeout (`asyncio.wait_for`) is added in Phase 2 and tested with a genuinely slow fake provider.
- **Alternative:** Mock sleeps past the timeout (more realistic, slower tests).

## D15. Request ID generated in middleware: **Default** (Phase 1)
- **Why:** The ID exists before validation or auth runs, so every error response, including validation and 404s, carries the same `request_id` as the `X-Request-ID` header.
- **Alternative:** Generate per route (would miss errors raised before the route).
