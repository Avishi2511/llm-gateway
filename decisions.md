# Decision Log

Running record of design decisions for SecureLLM Gateway: what was chosen, why, and the alternatives, so changes can be made later with context.
Source requirements: `product-spec-mvp.md`. Build plan: `plan.md`.

Status values: **Decided**, **Open** (needs an answer), **Default** (chosen by Claude, easy to change).

---

## D1. Real LLM provider: Anthropic: **Default** (chosen by Claude in Phase 2; user had not picked)
- **Context:** The spec requires one real provider adapter plus a mock.
- **Options:** Anthropic (Claude), OpenAI, Google Gemini.
- **Decision:** Anthropic via the official `anthropic` SDK. User did not answer, so I used my earlier recommendation to avoid blocking Phase 2.
- **Default model:** `claude-opus-5-5` (`ANTHROPIC_DEFAULT_MODEL`), the SDK-skill default. Cheaper options: `claude-sonnet-5-5`, `claude-haiku-5-5`, just a config change.
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

## D16. Anthropic adapter rejects `temperature`: **Default** (Phase 2)
- **Why:** The installed SDK (1.13) has no `temperature` parameter, and current Claude models reject non-default sampling values. The spec says unsupported features must be rejected, not silently ignored, so the adapter raises `UNSUPPORTED_FEATURE` (400) before calling the API. The mock provider still accepts it.
- **Alternatives:** Silently drop it (violates spec); send via `extra_body` for older models that accept it (model-specific logic).

## D17. `provider_mode=real` derives the default alias: **Default** (Phase 2)
- **Behaviour:** If `MODEL_ALIASES` is not set explicitly, real mode maps `default` to `anthropic` / `ANTHROPIC_DEFAULT_MODEL`. The Anthropic adapter is built only if an enabled alias uses it, and then requires `ANTHROPIC_API_KEY` (fails at startup otherwise).
- **Alternatives:** Always require explicit `MODEL_ALIASES`.

## D18. Wall-clock timeout in the service, plus SDK timeout: **Default** (Phase 2)
- **Why:** `asyncio.wait_for` guarantees the limit for any provider, including ones with no timeout of their own. The SDK timeout is also set so connections are released.

## D19. Effort set to `low` by default; refusal fallbacks not enabled: **Default** (Phase 2)
- **Effort:** `claude-opus-5-5` always thinks, and thinking tokens count against `max_tokens` (capped at 1024 here), so `low` avoids empty replies. `ANTHROPIC_EFFORT` is configurable; leave it empty for models without effort support.
- **Refusal fallbacks:** The API offers an opt-in server-side fallback for safety refusals. Not enabled, to keep the MVP small; a refusal surfaces as `finish_reason: "refusal"`. Can be added in the adapter via the beta client.
- **Retries:** `PROVIDER_MAX_RETRIES` (0 or 1, default 0) is passed to the SDK, which retries only transient errors.

## D20. System messages sent via Anthropic's `system` parameter: **Default** (Phase 2)
- **Why:** The Anthropic API takes system prompts as a separate field. All `system` messages are joined in order; messages must then start with a `user` message, otherwise the adapter returns `INVALID_REQUEST`.

## D21. Guardrail order and short-circuit: **Default** (Phase 3)
- **Behaviour:** injection patterns → custom prohibited patterns → PII. A block returns immediately and records only that check id; redaction never runs on blocked input, so no partial findings are recorded for it.
- **Alternatives:** Run all checks and report every finding (more informative, but more detail about blocked content).

## D22. Which roles are scanned: **Default** (Phase 3)
- **Behaviour:** Injection patterns scan `user` and `assistant` messages, not the caller's `system` messages. Custom prohibited patterns and PII redaction scan every role.
- **Why:** Callers legitimately write instructions in system messages, but anything a caller sends is untrusted for PII purposes.
- **Alternative:** Scan all roles for injection too (more false positives on legitimate system prompts).

## D23. Phone detection requires separators or a leading `+`: **Default** (Phase 3)
- **Behaviour:** Matches `(555) 010-0100`, `555-010-0100`, `555.010.0100`, `+1 ...`, and `+`-prefixed international numbers with 8-15 digits. A bare run of digits (`5550100100`) is not matched.
- **Why:** Avoids redacting order numbers, IDs and timestamps. Known false negative, covered by a test.
- **Alternative:** Match any 10-digit run (higher recall, more false positives).

## D24. Injection patterns are a short high-confidence list: **Decided by spec** (Phase 3)
- Three pattern groups (ignore/override instructions, reveal system prompt, jailbreak persona) in `app/guardrails/patterns.py`. Known false positives and negatives are documented in `tests/corpus/samples.py` and asserted in tests so the limits stay visible. Do not claim complete detection.

## D25. Request size enforcement: **Default** (Phase 3)
- **Behaviour:** Middleware rejects bodies whose `Content-Length` exceeds `MAX_REQUEST_BYTES` (413). Per-message length and message-count limits are enforced in the service for all clients, including chunked uploads without `Content-Length`. Errors use `REQUEST_TOO_LARGE`.
- **Limitation:** A chunked upload with no `Content-Length` is still read fully before the per-message checks run; a real deployment should also set a body limit at the reverse proxy.
- **Alternative:** Stream-count bytes in a pure ASGI middleware (more code).

## D26. Output block is HTTP 502 `OUTPUT_BLOCKED`; input block is 400 `INPUT_BLOCKED`: **Default** (Phase 3)
- **Why:** An input block is the caller's request being rejected; an output block is the upstream response being rejected.
- **Alternative:** 403 for both.

## D27. Canary is configurable and case-insensitive: **Default** (Phase 3)
- `OUTPUT_CANARY` (default `CANARY-SECRET-0000`; empty disables it) plus regexes in `OUTPUT_BLOCK_PATTERNS`. The mock's `unsafe` behaviour emits the configured canary so the demo works with any value. Invalid regexes fail at startup.
