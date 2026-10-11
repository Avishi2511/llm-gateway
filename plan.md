# SecureLLM Gateway: Detailed Build Plan

- Requirements source: `product-spec-mvp.md`
- **Design decisions, rationale and alternatives: `decisions.md`.** Check it before changing any approach below. New decisions made while building get appended there.
- Status of the real LLM vendor: **open** (decision D1). Everything except the Phase 2 adapter is vendor-independent.

---

## 1. Goal and guiding principles

Build one small FastAPI service that accepts chat requests, applies input guardrails, calls a configured LLM provider, applies output guardrails, records safe usage metadata, and returns a normalized response.

Principles that drive every design choice:
1. **Guardrails must be provably enforced.** Blocked input never reaches the provider. Blocked output never reaches the client. Tests prove it by inspecting the mock provider.
2. **Never leak.** No raw prompts, completions, matched sensitive values, API keys, stack traces or SDK errors appear in responses, logs, or the database.
3. **Orchestration is independent of HTTP.** Core logic is a plain function/class that can be tested without a server.
4. **Everything works without credentials.** Mock mode is the default; tests never need a vendor key.
5. **Small and finished beats large and half-done.** Follow the spec's scope rule: nothing beyond the must-haves until the core path and its tests are complete.

---

## 2. Request lifecycle (authoritative flow)

For every `POST /v1/chat/completions`:

| # | Step | Failure → error code (HTTP) | Provider called? |
|---|---|---|---|
| 1 | Generate `request_id` (`req_<random>`), start timer | n/a | no |
| 2 | Authenticate `Authorization: Bearer <key>` | `UNAUTHORIZED` (401) | no |
| 3 | Validate payload (schema, roles, size limit, unsupported features) | `INVALID_REQUEST` (400/422), `REQUEST_TOO_LARGE` (413), `UNSUPPORTED_FEATURE` (400) | no |
| 4 | Per-key rate limit | `RATE_LIMITED` (429) | no |
| 5 | Resolve model alias | `UNKNOWN_MODEL` (400/404) | no |
| 6 | Input guardrails → `allow` / `redact` / `block` | `INPUT_BLOCKED` (400/403) | no |
| 7 | Provider call with finite timeout | `PROVIDER_ERROR` (502), `PROVIDER_TIMEOUT` (504) | yes |
| 8 | Output guardrails | `OUTPUT_BLOCKED` (502/403), response discarded | yes, but output dropped |
| 9 | Write safe metadata row | (DB failure is logged and does not alter the response; see 6.4) | n/a |
| 10 | Return normalized response | n/a | n/a |

Order note: auth precedes validation so unauthenticated callers get no information about the schema. Rate limiting follows validation so malformed requests don't need to be counted, and precedes the expensive steps. Exact ordering of 3 and 4 is recorded in `decisions.md` if changed.

Every outcome, including failures at steps 2–8, produces a `request_logs` row where a request id exists. (Decision D11.) Step 2 failures are logged without a key id.

---

## 3. Project layout

```
llm-gateway/
  app/
    __init__.py
    main.py              # create_app(), middleware, exception handlers, router wiring
    config.py            # Settings (pydantic-settings), alias map, guardrail config
    schemas.py           # ChatRequest, Message, ChatResponse, Usage, ErrorResponse, ModelInfo, UsageRecord
    errors.py            # GatewayError base + subclasses, code/status/message table
    logging_setup.py     # structured logging, redaction-safe formatter
    api/
      __init__.py
      deps.py            # auth dependency, service/db dependencies
      chat.py            # POST /v1/chat/completions
      meta.py            # GET /health, GET /v1/models, GET /v1/usage
    gateway/
      __init__.py
      service.py         # GatewayService.handle_chat(...): the orchestration
      aliases.py         # alias → (provider, provider_model) resolution
    providers/
      __init__.py
      base.py            # Provider Protocol, ProviderResult, ProviderError types
      mock.py            # deterministic mock
      <vendor>.py        # real adapter (vendor TBD, D1)
      registry.py        # name → provider instance from settings
    guardrails/
      __init__.py
      types.py           # Action enum, CheckResult, GuardrailDecision
      input.py           # size, PII detect/redact, injection patterns, custom prohibited patterns
      output.py          # canary and blocked-pattern checks
      patterns.py        # compiled regexes and pattern lists, kept in one place
    ratelimit.py         # in-memory per-key limiter
    db/
      __init__.py
      models.py          # RequestLog (SQLAlchemy)
      session.py         # engine/session factory
      repo.py            # UsageRepository: record(), recent()
  tests/
    conftest.py          # app factory with mock provider, in-memory SQLite, fixtures
    unit/                # guardrails, aliases, limiter, error mapping, config
    api/                 # endpoint tests with TestClient
    corpus/              # synthetic benign / PII / injection / canary samples
  scripts/
    demo.py              # runs the demo scenarios from §12 of the spec against a running server
  .env.example
  requirements.txt
  requirements-dev.txt
  README.md
  plan.md  decisions.md  product-spec-mvp.md
```

Module boundaries: `api/` knows HTTP. `gateway/service.py` knows the pipeline but not FastAPI. `guardrails/`, `providers/`, `ratelimit.py` and `db/` know nothing about each other; the service wires them together. Empty placeholder modules are not created ahead of need.

---

## 4. Configuration

All settings are loaded once via `pydantic-settings` from environment variables (and an optional local `.env`, git-ignored). Validated at startup; invalid config fails fast with a clear message.

| Variable | Purpose | Default |
|---|---|---|
| `GATEWAY_API_KEYS` | Comma-separated list of accepted gateway keys (D5) | none; required unless `AUTH_DISABLED` for local dev is explicitly decided |
| `PROVIDER_MODE` | `mock` or `real` | `mock` |
| `<VENDOR>_API_KEY` | Vendor credential, env only | unset |
| `MODEL_ALIASES` | Alias map (JSON or a small config file): `{"default": {"provider": "mock", "model": "mock-1"}}` | one `default` alias |
| `PROVIDER_TIMEOUT_SECONDS` | Hard timeout for provider call | 30 |
| `PROVIDER_MAX_RETRIES` | 0 or 1, bounded | 0 |
| `MAX_REQUEST_BYTES` | Max body size | 32768 |
| `MAX_MESSAGES` / `MAX_MESSAGE_CHARS` | Structural limits | 50 / 8000 |
| `MAX_OUTPUT_TOKENS_CAP` | Server-side ceiling on client's `max_tokens` | 1024 |
| `RATE_LIMIT_PER_MINUTE` | Per-key requests/minute | 30 |
| `PII_REDACTION_ENABLED` | Global redaction toggle (D4) | true |
| `INJECTION_CHECK_ENABLED` | Toggle injection patterns | true |
| `EXTRA_INPUT_BLOCK_PATTERNS` | Optional additional regexes | empty |
| `OUTPUT_BLOCK_PATTERNS` | Regexes blocking responses | includes the synthetic canary |
| `OUTPUT_CANARY` | Synthetic secret string, e.g. `CANARY-SECRET-0000` | set in `.env.example` |
| `DATABASE_URL` | SQLAlchemy URL | `sqlite:///./gateway.db` |
| `PRICING_JSON` (optional) | Per-model token prices for cost *estimate* | unset → cost stays null |
| `LOG_LEVEL` | Logging level | INFO |

Rules: aliases are server-side only; clients cannot pass provider names, model identifiers or credentials (spec FR-3). `.env` is git-ignored; `.env.example` has placeholders only.

---

## 5. API contract

### 5.1 `POST /v1/chat/completions` (must)
Request:
```json
{
  "model": "default",
  "messages": [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Hello"}
  ],
  "temperature": 0.7,
  "max_tokens": 256
}
```
- `model`: required logical alias.
- `messages`: 1..`MAX_MESSAGES`; roles limited to `system`, `user`, `assistant`; `content` is a non-empty string only (multimodal lists rejected).
- `temperature`: optional, 0.0–2.0. `max_tokens`: optional, positive, clamped to the server cap.
- Unsupported fields (`stream`, `tools`, `tool_choice`, `functions`, image content, etc.) → `UNSUPPORTED_FEATURE`, never silently ignored. `stream: false` is accepted; `stream: true` is rejected. Unknown extra fields are rejected (`extra="forbid"`) so typos aren't silently dropped.

Response (flat, D6):
```json
{
  "request_id": "req_abc123",
  "model": "default",
  "message": {"role": "assistant", "content": "..."},
  "usage": {"input_tokens": 12, "output_tokens": 30, "total_tokens": 42},
  "finish_reason": "stop",
  "guardrails": {"action": "redact", "checks": ["pii_email"]}
}
```
`usage` fields are `null` when the provider didn't report them. `guardrails` exposes only the action and check IDs, never matched text. `X-Request-ID` is also returned as a header.

### 5.2 Other endpoints
- `GET /health` (must, unauthenticated): `{"status": "ok"}`; includes the provider mode, no secrets.
- `GET /v1/models` (should, authenticated): lists configured aliases only (no provider model ids or credentials).
- `GET /v1/usage?limit=50` (should, authenticated): recent safe request records (see 7). Bounded `limit`; scoped so a key sees only its own records.
- `/docs` and `/openapi.json`: FastAPI-generated.

### 5.3 Error format (single envelope)
```json
{"error": {"code": "INPUT_BLOCKED", "message": "The request was blocked by the configured policy.", "request_id": "req_abc123"}}
```
Error table (code → HTTP → fixed message):

| Code | HTTP | Meaning |
|---|---|---|
| `UNAUTHORIZED` | 401 | Missing/invalid key (identical message for both) |
| `INVALID_REQUEST` | 422 | Schema/validation failure (field names only, never values) |
| `REQUEST_TOO_LARGE` | 413 | Body or message limits exceeded |
| `UNSUPPORTED_FEATURE` | 400 | Streaming, tools, multimodal |
| `UNKNOWN_MODEL` | 400 | Alias not configured/enabled |
| `INPUT_BLOCKED` | 400 | Input guardrail block |
| `OUTPUT_BLOCKED` | 502 | Generated output rejected and discarded |
| `RATE_LIMITED` | 429 | Includes `Retry-After` header |
| `PROVIDER_ERROR` | 502 | Normalized upstream failure |
| `PROVIDER_TIMEOUT` | 504 | Upstream exceeded the timeout |
| `INTERNAL_ERROR` | 500 | Catch-all; generic message, details only in server logs without sensitive data |

Handlers cover `GatewayError`, FastAPI `RequestValidationError`, `HTTPException`, and bare `Exception`, all mapped to this envelope. Exact HTTP statuses for blocks are noted in `decisions.md` if debated.

---

## 6. Component design

### 6.1 Providers (`providers/`)
```python
class Provider(Protocol):
    name: str
    async def complete(self, messages: list[Message], model: str,
                       temperature: float | None, max_tokens: int | None,
                       timeout_s: float) -> ProviderResult: ...

@dataclass
class ProviderResult:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str | None
```
- Providers raise only `ProviderTimeoutError` or `ProviderUpstreamError` (own types, no SDK exception leaking, no raw messages). The service maps them to `PROVIDER_TIMEOUT` / `PROVIDER_ERROR`.
- **Mock provider:** deterministic echo-style reply (e.g. `"Mock reply to: <last user message hash/len>"` or a fixed string), fake token counts derived from lengths. Behaviours selectable via config or constructor: `success`, `fail`, `timeout` (sleeps past the timeout), `unsafe` (returns the canary). Records `call_count` and the exact messages it received so tests can assert redaction happened and block paths made zero calls.
- **Real adapter (vendor TBD):** wraps the official SDK, passes the alias-resolved model id, applies the timeout, maps SDK exceptions to the two error types, maps the SDK's usage fields into `ProviderResult`. Optional single bounded retry on transient errors only (off by default).
- `registry.py` builds provider instances from settings so `PROVIDER_MODE=mock` needs no vendor package or key.

### 6.2 Aliases (`gateway/aliases.py`)
`resolve(alias) -> ResolvedModel(provider_name, provider_model)`; raises `UnknownModelError`. Disabled aliases behave as unknown. Optional fallback target is a stretch goal and not built.

### 6.3 Guardrails (`guardrails/`)

**Types**
```python
class Action(str, Enum): ALLOW, REDACT, BLOCK
@dataclass
class CheckResult: check_id: str; action: Action; count: int   # no matched text
@dataclass
class GuardrailDecision:
    action: Action                  # overall = strongest of the checks (BLOCK > REDACT > ALLOW)
    checks: list[CheckResult]
    messages: list[Message] | None  # transformed messages when REDACT
```

**Input checks (run in order; block short-circuits):**
1. *Structure/size* (also enforced at the API layer): role set, non-empty content, per-message and total character limits.
2. *Prompt-injection heuristics* (`injection_pattern`): small list of high-confidence, case-insensitive phrases, e.g. "ignore (all )?(previous|prior) instructions", "disregard the system prompt", "reveal your system prompt", "you are now DAN". Match → `BLOCK` (D3). Only applied to `user` (and `assistant`/tool-supplied) content, not the server's configured system prompt if any. Documented as defense-in-depth with known false positives/negatives.
3. *Custom prohibited patterns* from config → `BLOCK`.
4. *PII detection:* email regex and a conservative phone regex (international and US-style formats, requiring enough digits to avoid matching ordinary numbers). If `PII_REDACTION_ENABLED`: replace with `[REDACTED_EMAIL]` / `[REDACTED_PHONE]` and return `REDACT`. If disabled: record the finding as `ALLOW` with check ids and leave content untouched (D4).

Redaction operates on every message. The original values are never logged or stored; only category and count are. The provider receives only the transformed messages.

**Output checks (`output.py`):** run on the provider's `content`: the configured canary string and `OUTPUT_BLOCK_PATTERNS`. Any match → `BLOCK`; the service drops the content, returns `OUTPUT_BLOCKED`, and records only the check id.

All guardrails are pure functions of text and config, so they unit-test without I/O.

### 6.4 Orchestration (`gateway/service.py`)
`GatewayService(settings, providers, guardrails, limiter, repo)`.

`async def handle_chat(request: ChatRequest, key_id: str, request_id: str) -> ChatResponse`:
1. Rate-limit check for `key_id`.
2. Resolve alias.
3. Run input guardrails; on `BLOCK` raise `InputBlockedError` (provider untouched).
4. Call provider (with timeout) using the guardrail-transformed messages.
5. Run output guardrails on the result; on `BLOCK` raise `OutputBlockedError` and discard.
6. Build `ChatResponse`.
7. In a `finally`, record a metadata row (status, duration, tokens, guardrail action, error code). A DB failure is caught and logged (without sensitive data) so persistence trouble doesn't change the client-visible result.

Structure guarantees that no exception path returns provider output: the only code path producing a `ChatResponse` is after the output check passes. This is covered by a dedicated test that makes the output checker raise and asserts the client gets an error, not content.

### 6.5 Auth (`api/deps.py`)
- Parse `Authorization: Bearer <key>`; compare against the configured keys with `secrets.compare_digest`.
- Missing/malformed/invalid → `UNAUTHORIZED` with the same message.
- On success, derive `key_id` = first 8 hex chars of SHA-256(key); this id is used for rate limiting and usage. The raw key is never stored or logged.
- `/health` is unauthenticated; docs endpoints follow spec guidance (left open for local demo; noted in README).

### 6.6 Rate limiting (`ratelimit.py`)
- In-memory, per `key_id`, thread/async-safe (lock or single-event-loop discipline).
- Algorithm: sliding-window log or fixed window per minute (leaning to sliding window for accurate behaviour; choice recorded in `decisions.md`).
- Clock is injectable so tests can verify the limit and the reset without sleeping.
- Exceeding → `RATE_LIMITED` with `Retry-After`.
- Documented limitation: per-process only, not distributed.

### 6.7 Persistence (`db/`)
Table `request_logs` (spec §8):

| Column | Type | Notes |
|---|---|---|
| `id` | PK | internal |
| `request_id` | str, unique, indexed | `req_...` |
| `created_at` | datetime (UTC) | |
| `key_id` | str, nullable | hashed key prefix |
| `model_alias` | str, nullable | |
| `status` | str | `success`, `blocked_input`, `blocked_output`, `provider_error`, `timeout`, `rate_limited`, `invalid` ... |
| `duration_ms` | int | |
| `input_tokens`, `output_tokens` | int, nullable | null when unknown, never guessed |
| `estimated_cost` | float, nullable | only if usage and pricing config both exist; labelled an estimate |
| `guardrail_action` | str, nullable | |
| `guardrail_checks` | str/JSON, nullable | check ids only |
| `error_code` | str, nullable | |

No prompt, completion, or matched-value columns exist. Tables are created at startup (`create_all`); migrations (Alembic) are deferred as unnecessary at this size. `UsageRepository.record()` and `.recent(key_id, limit)`.

### 6.8 Logging (`logging_setup.py`)
Structured key-value logs with `request_id`, `key_id`, `alias`, `status`, `duration_ms`, `error_code`, `guardrail_checks`. A filter ensures `Authorization` headers and message bodies are never logged. No logging of request/response bodies at any level.

---

## 7. Phased delivery

Each phase finishes with passing tests and the spec's exit criteria before moving on. Suggested one commit (or a small series) per phase.

### Phase 1: API skeleton and mock path
**Build:** repo scaffolding (`.gitignore` including `.env`, `*.db`, venv), `requirements*.txt`, `config.py`, `schemas.py`, `errors.py` + handlers, request-ID middleware, `providers/base.py` + `mock.py`, `GatewayService` with the bare pipeline (alias lookup, provider call, response), `/health`, `/v1/chat/completions`, `conftest.py`.
**Tests:** valid request returns deterministic mock completion; invalid payload (bad role, empty messages, extra field) returns the error envelope; `stream: true` returns `UNSUPPORTED_FEATURE`; health OK; every error has `request_id`.
**Exit:** endpoint returns a deterministic mock completion and basic API tests pass.

### Phase 2: Aliases, real provider, timeouts
**Build:** alias config + `UnknownModelError`; provider registry; real vendor adapter (D1) with SDK exception mapping; timeout enforcement (`asyncio.wait_for` as a backstop on top of SDK timeout); optional bounded retry (default off); `.env.example`.
**Tests:** unknown alias rejected with no provider call; client cannot supply provider/credentials; mock `fail` → `PROVIDER_ERROR`; mock `timeout` → `PROVIDER_TIMEOUT`; adapter error-mapping unit tests using a faked SDK client (no network). Optional manual smoke test against the real vendor, excluded from CI by marker.
**Exit:** same endpoint works with mock or real provider purely by configuration.

### Phase 3: Guardrails
**Build:** size and structure limits; PII detection/redaction; injection patterns; custom patterns; output canary and block patterns; wiring into the service; guardrail summary in the response.
**Tests (critical):** email and phone redacted and the *mock records redacted text*, never the original; redaction off → passes through, check recorded; injection input → `INPUT_BLOCKED` with `mock.call_count == 0`; mock `unsafe` → `OUTPUT_BLOCKED` and the canary text is absent from the response body, headers, and logs; output checker raising → error, not content; oversized request → `REQUEST_TOO_LARGE`; error bodies don't contain matched values. Corpus-driven parametrized tests with benign text and known false-positive cases documented.
**Exit:** critical guardrail tests pass.

### Phase 4: Auth, rate limiting, usage
**Build:** API-key dependency with multi-key support (D5); limiter with injectable clock; `request_logs` model/repo; service `finally` recording; `/v1/models`; `/v1/usage`; optional cost estimate from pricing config.
**Tests:** missing/invalid/wrong-scheme key → 401 with the same message; valid second key works; rate limit → 429 after threshold with `Retry-After`, resets after the window, independent per key; usage rows exist for success and for blocked/failed requests; rows contain no prompt/completion/raw key; tokens null when provider reports none; `/v1/usage` is scoped per key; logs captured with `caplog` contain no keys or synthetic sensitive values.
**Exit:** auth, rate limits and usage behaviour tested.

### Phase 5: Polish and demo
**Build:** README (overview, architecture diagram from the spec's mermaid, setup, env vars, curl examples with sample responses, running tests, supported request subset, limitations/future work); `scripts/demo.py` exercising each demo-checklist item; `.env.example` review; clean-checkout test run; optional latency baseline against the mock (no performance claims); resume bullet only for what's implemented.
**Exit:** a reviewer can run the project and reproduce the main scenarios unassisted.

### Priority order if time is tight (from the spec)
Mock path → one real provider → guardrails with tests → auth + safe errors → usage history → rate limiting → polish.

---

## 8. Test strategy

- **Unit (no HTTP):** guardrail decisions, redaction output, pattern boundaries, alias resolution, limiter (fake clock), error mapping, config validation, adapter exception mapping.
- **API (TestClient/HTTPX):** all must-have scenarios from the spec §10 through the real app with the mock provider and an in-memory SQLite database; each test builds a fresh app so limiter and DB state don't bleed.
- **Proof-of-control tests:** assertions on `mock.call_count` and on the exact messages the mock received; assertions that canary/PII strings are absent from responses, DB rows and captured logs.
- **Synthetic corpus** in `tests/corpus/`: benign prompts, PII samples (obviously fake: `jane.doe@example.com`, `+1 555-0100`), injection phrases, canary outputs, plus false-positive examples that document known limitations.
- **Not tested here:** real vendor calls (manual, marker-gated), performance beyond an optional mock baseline.
- Coverage target is a sanity check on guardrail and service modules, not a headline metric.

---

## 9. Security and privacy checklist

- Secrets only in environment; `.env` git-ignored; `.env.example` placeholders only.
- Constant-time key comparison; raw keys never logged or stored.
- Input block happens before any provider call; output block before any response.
- Error responses use fixed messages; no SDK text, stack traces, or matched content.
- Request-size limits and a server-side `max_tokens` cap to bound abuse and cost.
- Synthetic data only in tests, fixtures, and demos.
- Known limits stated plainly in the README: regex heuristics are not complete detection; the rate limiter is single-instance; cost is an estimate.

---

## 10. Definition of done (maps to spec §12)

- [ ] Normal chat request returns a response
- [ ] Mock mode works without credentials
- [ ] Real provider works when configured
- [ ] Missing/invalid key → 401
- [ ] Email/phone redacted before provider invocation
- [ ] Injection pattern blocked before provider invocation
- [ ] Unsafe mock output blocked before reaching the client
- [ ] Provider timeout/failure → safe error
- [ ] Over-limit requests → 429
- [ ] Usage inspectable without raw prompt/completion storage
- [ ] Full test suite passes with no real provider key
- [ ] README, `.env.example`, demo script, architecture diagram, limitations present

---

## 11. Open items

- **D1: real provider vendor** (needed before Phase 2's adapter).
- Rate-limit algorithm (sliding vs fixed window) and exact HTTP codes for blocks: to be recorded in `decisions.md` when implemented.
- Whether `/docs` should require a key: default open for local demos.
