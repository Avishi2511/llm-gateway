# SecureLLM Gateway — Product Specification

**Document type:** Product Requirements Document (PRD), Software Requirements Specification (SRS), and Technical Architecture Specification  
**Version:** 1.0  
**Status:** Implementation baseline for a portfolio-grade, production-inspired project  
**Audience:** Product owner, backend engineers, security engineers, QA, DevOps, and technical reviewers

---

## 1. Executive Summary

SecureLLM Gateway is a centralized, policy-driven platform that provides applications with a consistent and secure interface to multiple large language model (LLM) providers. It combines an LLM gateway and a guardrails engine into one integrated product while preserving strict internal module boundaries.

The platform must provide:

- A unified API for supported LLM providers.
- Authentication and tenant-aware authorization.
- Configurable input and output guardrails.
- Model aliases, routing, bounded retries, and controlled fallback.
- Per-client rate limits, token limits, and budget controls.
- Usage, cost, latency, error, and policy-decision observability.
- Versioned policy configuration and auditable administrative changes.
- Automated tests, local deployment, documentation, and reproducible demos.

The system is intended to be credible as a portfolio project and designed with production engineering principles. It must not claim that prompt-injection detection is perfect, that the system is certified for regulatory compliance, or that a finite test suite proves security against all attacks.

### 1.1 Product vision

**One API. Multiple models. Centralized control.**

Applications should not need to manage provider-specific SDKs, provider credentials, guardrail implementations, retry policies, or usage accounting independently. SecureLLM Gateway centralizes those capabilities and exposes a stable client-facing contract.

### 1.2 Business problems

The product addresses the following problems:

1. Applications integrate with LLM providers in inconsistent ways.
2. Sensitive data may be sent to external providers unintentionally.
3. Prompt injection, unsafe outputs, and content-policy violations are handled inconsistently.
4. Organizations lack consolidated visibility into model usage and spend.
5. Applications become coupled to one provider or model API.
6. Provider failures and policy decisions are difficult to investigate.
7. Platform and security teams lack a central enforcement point.

### 1.3 Goals

- Provide a stable API over multiple LLM providers.
- Inspect requests and responses using explicit, testable policies.
- Route requests by logical model alias and configured rules.
- Handle transient failures with bounded retries and safe fallback.
- Isolate organizations, projects, and API clients.
- Track usage, estimated cost, latency, errors, and guardrail decisions.
- Version, test, publish, and audit policies.
- Deliver a documented local deployment and repeatable demonstration.

### 1.4 Non-goals for version 1

- Training or fine-tuning foundation models.
- Building a foundation model.
- Guaranteeing perfect prompt-injection detection.
- Arbitrary agent execution or unrestricted tool calling.
- Replacing a full enterprise identity provider.
- Regulatory certification or guaranteed compliance.
- Multi-region active-active deployment.
- Supporting every provider or every provider-specific feature.
- A full enterprise billing and invoicing system.

---

## 2. Users, Roles, and Domain Model

### 2.1 User personas

| Persona | Needs | Capabilities |
|---|---|---|
| Application developer | Integrate AI features quickly | Invoke API, select logical model aliases, inspect own usage |
| Platform engineer | Operate model access | Configure providers, routing, health, and reliability settings |
| Security engineer | Enforce AI policies | Configure guardrails, review events, test policies |
| Organization administrator | Govern access and spend | Manage projects, clients, quotas, budgets, and permissions |
| Auditor / analyst | Investigate behavior | Read-only access to authorized usage and audit records |

Roles must be explicit and permission-checked on the server. Knowing a resource identifier must never grant access to it.

### 2.2 Resource hierarchy

The logical hierarchy is:

1. **Organization / tenant** — isolation boundary, organization-level policies, aggregate budgets.
2. **Project / workspace** — environment, approved models, default policy, project budget.
3. **API client** — credential, permissions, rate limits, client usage.
4. **Request** — request ID, selected policy version, routing outcome, usage, and final result.

Every organization-owned record must include a tenant identifier. All queries and mutations must enforce tenant scope using the authenticated principal, never a caller-supplied tenant ID alone. PostgreSQL row-level security may be added as defense in depth but must not replace application authorization.

### 2.3 Operating modes

- **Development:** Mock provider supported; external provider credentials optional for tests.
- **Standard:** Normal authentication, configured policies, routing, quotas, and observability.
- **Restricted:** Reduced provider allowlist, stricter policies, conservative fallback, and mandatory security audit events.
- **Administrative:** Separate authenticated management APIs for policy and configuration changes.

Modes must be configuration profiles, not scattered hardcoded branches.

---

## 3. Architecture Requirements

### 3.1 Architecture style

Implement a **modular monolith with asynchronous I/O**. Do not split the initial system into microservices prematurely.

Deploy one API application with strict module boundaries, PostgreSQL for durable state, Redis for rate counters and short-lived coordination, and optional worker processes for background work. This minimizes operational overhead while keeping modules independently testable and extractable later.

### 3.2 Logical components

1. **API edge**
   - HTTP routing, request validation, request ID creation, body-size limits.
   - Authentication and authorization.
   - Rate limiting and request deadlines.
2. **Gateway orchestrator**
   - Request lifecycle coordination.
   - Policy snapshot resolution.
   - Model alias resolution and route selection.
   - Retry/fallback orchestration.
3. **Guardrails engine**
   - Input inspection.
   - Output inspection.
   - PII detection and optional redaction.
   - Prompt-injection signals.
   - Content policy checks.
   - Structured-output validation.
   - Decision aggregation and explanation codes.
4. **Provider adapters**
   - Provider-specific API integration.
   - Normalized requests and responses.
   - Timeouts, provider error mapping, and usage extraction.
5. **Policy and configuration service**
   - Policy CRUD, versioning, validation, publication, rollback.
   - Provider and model configuration.
6. **Usage and cost service**
   - Token usage normalization.
   - Versioned pricing data.
   - Cost estimates, quotas, and budgets.
7. **Persistence**
   - Tenant and project metadata.
   - API client metadata and credential hashes.
   - Policies and versions.
   - Usage, audit events, and request metadata.
8. **Observability**
   - Structured logs, metrics, traces, and audit events.
9. **Admin API**
   - Role-protected configuration and reporting endpoints.

### 3.3 Request lifecycle

For a non-streaming request, the required order is:

1. Generate or validate a correlation/request ID.
2. Enforce transport-level limits, content type, and request size.
3. Authenticate the API client.
4. Resolve organization, project, and permissions from trusted server-side identity.
5. Apply rate limits and preliminary quota checks.
6. Validate the request schema and requested options.
7. Resolve a versioned policy snapshot.
8. Run input guardrails.
9. If blocked or escalated, stop before any provider call.
10. Resolve logical model alias and approved route.
11. Check spend/token budget and route eligibility.
12. Call the provider with a deadline and bounded retry policy.
13. Normalize the provider response and usage metadata.
14. Run output guardrails.
15. Validate structured output if requested.
16. Apply configured redaction or reject the response if required.
17. Persist usage and security decision metadata.
18. Return the normalized response with request ID and safe metadata.
19. Emit metrics and trace events.

Observability must span the entire lifecycle. Security and usage events should be recorded at the relevant stages, not only at response time.

### 3.4 Sequence and policy invariants

- Input guardrails must run before any provider call.
- Output guardrails must run before the response reaches the client.
- A guardrail block must not trigger provider retries or fallback.
- Client input must never directly choose an unapproved provider endpoint.
- Provider credentials must remain server-side.
- Fallback must only use providers/models allowed by the resolved policy.
- The same request must not be retried indefinitely.
- All provider calls must have explicit timeouts and an overall deadline.
- Tenant identity must come from authenticated context, not request body fields.
- Policy decisions must reference the policy version used.
- Raw prompts and outputs must not be logged by default.
- No model-generated content may execute commands or tools in version 1.

### 3.5 Suggested deployment architecture

**Local / portfolio deployment:**

- `gateway-api`: FastAPI application.
- `postgres`: Durable relational data.
- `redis`: Rate-limit counters and short-lived coordination.
- `prometheus`: Metrics scraping.
- `grafana`: Metrics dashboards.
- Optional `otel-collector`: Trace collection.
- Optional `mock-provider`: Deterministic testing service.

Use Docker Compose for local development. The API must also support tests with mocked dependencies without requiring real provider credentials.

---

## 4. Technology Decisions

| Concern | Default choice | Rationale |
|---|---|---|
| Language | Python 3.12+ | Strong ecosystem and developer productivity |
| HTTP API | FastAPI | Typed APIs and OpenAPI documentation |
| Schemas | Pydantic | Validation at API and internal boundaries |
| Provider integration | LiteLLM or explicit provider adapters | Reduce provider integration work while retaining gateway-owned policy |
| PII detection | Microsoft Presidio plus custom recognizers | Configurable entity detection and redaction |
| Database | PostgreSQL | Durable relational data and transactions |
| ORM/migrations | SQLAlchemy + Alembic | Explicit schema evolution |
| Rate limiting | Redis | Shared counters across API instances |
| Tests | pytest + HTTPX | Unit and API/integration tests |
| Metrics | Prometheus | Operational metrics |
| Traces | OpenTelemetry | Cross-stage request tracing |
| Dashboards | Grafana | Demo and operations visibility |
| Packaging | Docker + Docker Compose | Reproducible local environment |
| CI | GitHub Actions | Automated lint, type checks, and tests |

The application must own its authorization, policy decisions, route permissions, cost controls, and audit logic. A provider-routing library may perform model calls, but it must not silently bypass the platform's guardrail lifecycle.

---

## 5. Public API Specification

The public API should be versioned and documented through OpenAPI. Use consistent error objects, request IDs, and status codes.

### 5.1 Required endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/v1/chat/completions` | Submit a non-streaming chat completion request |
| `GET` | `/v1/models` | List model aliases available to the authenticated client |
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe |
| `GET` | `/v1/usage` | Read authorized client/project usage |
| `GET` | `/admin/policies` | List policies, with admin authorization |
| `POST` | `/admin/policies` | Create a policy draft |
| `GET` | `/admin/policies/{policy_id}` | Retrieve policy and version metadata |
| `PUT` | `/admin/policies/{policy_id}` | Update a draft or policy configuration |
| `POST` | `/admin/policies/{policy_id}/publish` | Validate and publish a policy version |
| `POST` | `/admin/policies/{policy_id}/rollback` | Roll back to a previous version |
| `GET` | `/admin/audit-events` | Search authorized audit events |
| `GET` | `/admin/providers` | List configured providers and health metadata |

Admin endpoints must not be accessible to ordinary application clients. Mutations must create audit events.

### 5.2 Example request

```json
{
  "model": "balanced",
  "messages": [
    {
      "role": "user",
      "content": "Summarize this quarterly report."
    }
  ],
  "guardrails": {
    "enabled": true
  },
  "metadata": {
    "application": "demo-app"
  }
}
```

The server must ignore or reject client-supplied fields that attempt to override tenant identity, trusted policy IDs, provider credentials, or internal routing destinations. `metadata` must have size limits and must not be treated as trusted authorization input.

### 5.3 Example successful response

```json
{
  "id": "req_01JEXAMPLE",
  "model": "provider-a-model",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Here is the report summary."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 80,
    "total_tokens": 200
  },
  "gateway": {
    "request_id": "req_01JEXAMPLE",
    "guardrail_action": "allow",
    "policy_version": 3,
    "estimated_cost": 0.0012
  }
}
```

This is a proposed response contract, not a live response. The public format should remain stable even when the underlying provider changes. Cost is an estimate and must identify the pricing configuration/version used in stored usage records.

### 5.4 Error contract

All errors must use a predictable structure:

```json
{
  "error": {
    "code": "GUARDRAIL_BLOCKED",
    "message": "The request was blocked by an applicable safety policy.",
    "request_id": "req_01JEXAMPLE",
    "retryable": false
  }
}
```

Requirements:

- Never expose provider secrets, stack traces, internal prompts, or raw sensitive detection context.
- Return `401` for missing/invalid credentials and `403` for authenticated but unauthorized actions.
- Return `413` for request bodies exceeding configured limits.
- Return `422` for schema/semantic validation errors, unless a documented compatibility contract specifies otherwise.
- Return `429` for rate or quota limits.
- Return `502` for invalid or failed upstream responses where appropriate.
- Return `503` when no eligible provider is available.
- Return `504` for gateway deadline/timeouts where appropriate.
- Use a documented guardrail-block status consistently; `400` or `403` may be chosen, but clients must be able to identify the stable error code.
- Do not retry non-retryable errors.

### 5.5 API compatibility

- Maintain `/v1` compatibility.
- Do not expose raw provider response objects as the only response format.
- Provider-specific features must be explicitly represented or documented as unsupported.
- Reject unsupported options clearly rather than silently ignoring them.
- Include request IDs in response headers and response bodies.
- Publish OpenAPI documentation and runnable examples.

---

## 6. Model Routing and Provider Management

### 6.1 Provider abstraction

Define a provider interface that supports, at minimum:

- `generate(request, deadline) -> normalized_response`
- Provider/model capability metadata.
- Timeout and error normalization.
- Usage extraction.
- Health and availability metadata where supported.

A normalized response must include text or structured content, model identity, finish reason, token usage if available, and safe provider metadata. Provider-specific raw payloads should not leak into the public API.

### 6.2 Logical model aliases

Clients request approved aliases, for example:

- `fast`
- `balanced`
- `high_quality`

Each alias maps to an ordered set of eligible provider/model candidates and routing constraints. Alias definitions must be configurable rather than hardcoded in endpoint handlers.

### 6.3 Routing rules

The routing engine must consider:

1. Whether the model/provider is enabled.
2. Whether the authenticated tenant/project may use it.
3. Whether it supports the requested capabilities.
4. Whether it is currently eligible based on configured health/circuit state.
5. Policy restrictions and data-handling constraints.
6. Budget and request constraints.
7. Explicit routing preference or deterministic selection rules.

Do not route requests to an arbitrary endpoint supplied by the caller. Avoid automatic routing based solely on prompt contents unless that behavior is explicitly configured and audited.

### 6.4 Retry and fallback behavior

- Set connect timeout, read timeout, and overall request deadline.
- Use a small, configurable retry limit; default to at most two retries after the initial attempt.
- Use exponential backoff with jitter.
- Retry only transient failures and provider responses explicitly considered retryable.
- Respect provider retry hints where safe and compatible with the overall deadline.
- Do not retry malformed requests, authentication failures, guardrail blocks, or policy denials.
- Use fallback only to an approved candidate compatible with the request and policy.
- Avoid retrying non-idempotent operations unless the provider/request contract makes retry safe.
- Record attempts, selected route, fallback reason, and final outcome.
- Return a controlled error if all eligible providers fail.

### 6.5 Circuit breaker

A simple circuit breaker may be included after basic retries work. It should have closed, open, and half-open states, configurable failure thresholds, cooldown periods, and observable state transitions. It must not be used as a substitute for timeouts or bounded retries.

---

## 7. Guardrails Engine Specification

### 7.1 Design principles

The guardrails engine must be a first-class domain module with a consistent input/output contract. It must be testable without an LLM provider and must return structured decisions rather than scattered booleans.

Each evaluation result should include:

- `action`: `allow`, `block`, `redact`, or `escalate`.
- `stage`: `input` or `output`.
- `policy_id` and `policy_version`.
- Stable `rule_id` or detector identifier.
- Safe reason code.
- Confidence/severity where meaningful.
- Redacted/modified content when applicable.
- Evaluation duration.
- Optional internal diagnostic metadata that is never returned to untrusted clients.

### 7.2 Actions

- **ALLOW:** Continue processing without modifying the content.
- **BLOCK:** Stop processing and return a safe error; input blocks must occur before provider invocation.
- **REDACT:** Replace sensitive content with a configured placeholder and continue only if the policy permits.
- **ESCALATE:** Run a secondary check or require human review. In version 1, if no human-review workflow exists, escalation must resolve to a configured safe behavior—normally block or return a pending/review-required response. It must never silently allow the request.

### 7.3 Input guardrails

Required checks:

1. Schema and role validation.
2. Maximum body size, message count, and content length.
3. PII detection using Presidio and configurable recognizers.
4. Prompt-injection indicators using deterministic heuristics and optional classifier.
5. Configurable content policy checks.
6. Optional user/project-specific denied terms or patterns.
7. Input token/size limits and budget checks.

Input guardrails must inspect the full effective prompt context, including relevant message roles, while preserving role boundaries. Heuristics are signals, not proof of malicious intent. Policies should allow severity thresholds and configurable actions.

### 7.4 Output guardrails

Required checks:

1. PII detection and policy-based redaction/blocking.
2. Content policy checks where configured.
3. Maximum response length.
4. Structured-output validation against JSON Schema/Pydantic when requested.
5. Detection of invalid or empty provider responses.
6. Prevention of accidental exposure of internal error details or gateway metadata.

If output is blocked, the original unsafe response must not be returned to the client. The platform may return a safe refusal or a documented guardrail error, according to policy.

### 7.5 PII handling

- Support configurable entity types, including email, phone, and other supported Presidio entities.
- Support configurable actions per entity: allow, redact, or block.
- Redaction must be deterministic and testable.
- Do not assume every detector has equal accuracy for every locale or entity.
- Do not log unredacted PII by default.
- Include synthetic test cases for false positives and false negatives.
- Record entity type and action, not raw matched content, in normal audit records.

### 7.6 Prompt-injection handling

- Implement baseline deterministic patterns and optional classifier integration behind a common interface.
- Evaluate user-supplied text and relevant contextual messages.
- Do not treat detection as a guarantee of safety.
- Include benign adversarial-looking text in tests to measure false positives.
- Do not send requests to providers after a policy decision to block.
- Version detector configuration and record the version used.
- Never expose hidden detection prompts or internal policy implementation details in client-facing errors.

### 7.7 Policy precedence and aggregation

Policy evaluation must be deterministic. For version 1, use the following default precedence:

1. Hard platform/security denial.
2. Tenant/project mandatory policy.
3. Client-specific policy.
4. Optional application-level policy.
5. Default platform policy.

A lower-precedence policy must not weaken a higher-precedence mandatory denial. Define an explicit aggregation function: any mandatory `block` wins; `escalate` must not silently downgrade to `allow`; redaction can proceed only when all applicable policies permit it; otherwise block or escalate according to the stricter applicable rule.

Policies must be evaluated against an immutable version snapshot for the duration of one request.

### 7.8 Policy lifecycle

Policy states:

- `draft`
- `validated`
- `published`
- `disabled`
- `archived`

Requirements:

- Changes create a new version; do not overwrite history.
- Validate schemas and rule combinations before publishing.
- Support preview/dry-run evaluation against a test corpus.
- Publish atomically.
- Rollback by activating a previous version.
- Record actor, timestamp, change summary, and version in audit events.
- Cache published policy versions carefully; invalidate caches after publication.
- Requests already in progress may finish using their original snapshot.

---

## 8. Authentication, Authorization, and Secrets

### 8.1 API client authentication

For version 1, use server-issued API keys.

- Generate keys with a cryptographically secure random generator.
- Show the raw key only at creation time.
- Store a secure hash of the key, not the raw secret.
- Support revocation and rotation.
- Include key ID/prefix for lookup without storing the secret.
- Apply scopes/permissions to keys.
- Use constant-time comparison where applicable to credential verification.
- Never log credentials or return them from subsequent retrieval endpoints.

### 8.2 Administrative authorization

Use role-based access control with at least:

- `org_admin`
- `project_admin`
- `security_admin`
- `developer`
- `auditor`

Permissions must be enforced on every admin request and every resource query. Destructive or security-sensitive actions require audit events. The portfolio implementation may use database-backed users/roles or a clearly isolated local admin mechanism, but must not leave admin endpoints unauthenticated.

### 8.3 Provider secrets

- Load provider keys from environment variables or a secret manager.
- Do not commit secrets to source control.
- Do not store provider credentials in policy JSON or client-visible configuration.
- Avoid passing credentials through logs, traces, exception messages, or API responses.
- Document local `.env` setup using placeholders only.
- Support key rotation without code changes.

---

## 9. Rate Limits, Budgets, and Cost Accounting

### 9.1 Rate limiting

Support configurable limits at API-client and project levels:

- Requests per minute.
- Optional burst capacity.
- Token throughput or token allowance where practical.
- Separate administrative endpoint limits.

Redis counters must use atomic operations or scripts to avoid races. Define behavior when Redis is unavailable: for protected deployments, rate limiting must fail closed or use an explicitly configured safe local fallback. The default production-like profile should fail closed for enforcement-critical limits.

Return `429` with a stable error code and, where applicable, a retry hint. Do not reveal other clients' quota data.

### 9.2 Budgets

Support:

- Per-request maximum input/output token limits.
- Per-client daily or monthly budget.
- Project budget.
- Organization budget.
- Configurable hard or soft limits.

A hard budget must be enforced before provider invocation when a reliable preflight estimate is available. Because exact provider cost and token usage may not be known until after generation, define a reservation/reconciliation strategy:

1. Estimate the maximum or expected spend.
2. Reserve budget atomically when practical.
3. Execute the request.
4. Reconcile with provider-reported usage.
5. Release unused reservation or record the overage.
6. Prevent concurrent requests from bypassing budget through race conditions.

Do not claim exact hard spend enforcement when provider billing and token usage are not known in advance. Document the limits of estimates and any provider-specific uncertainty.

### 9.3 Cost estimation

- Maintain versioned pricing configuration per provider/model.
- Track input and output token counts separately.
- Prefer provider-reported usage where available.
- Mark estimates as estimates.
- Record pricing version and calculation inputs.
- Define behavior when usage is missing: mark cost as unknown or use a documented approximation.
- Do not hardcode prices throughout business logic.
- Make historical records reproducible using the pricing version active at the time.

---

## 10. Persistence and Data Model

Use PostgreSQL and migrations. The schema should be normalized enough to preserve ownership, versioning, and audit history.

### 10.1 Core tables

| Table | Purpose / important fields |
|---|---|
| `organizations` | `id`, `name`, `status`, timestamps |
| `projects` | `id`, `organization_id`, `name`, `environment`, `status` |
| `users` | Admin identities, status, timestamps |
| `memberships` | User-to-organization/project role assignments |
| `api_clients` | `id`, `organization_id`, `project_id`, `key_hash`, `key_prefix`, `status`, scopes |
| `providers` | Provider type, enabled state, safe configuration metadata |
| `model_aliases` | Alias, project/organization scope, routing configuration version |
| `guardrail_policies` | Policy identity, scope, current published version |
| `guardrail_policy_versions` | Immutable version, config JSON, author, validation result, timestamps |
| `request_records` | Request ID, tenant/project/client IDs, model alias, status, timing, policy version |
| `provider_attempts` | Request ID, provider/model, attempt number, outcome, duration, error category |
| `usage_records` | Request ID, token counts, pricing version, estimated cost |
| `guardrail_events` | Request ID, stage, policy/rule ID, action, safe reason code, duration |
| `audit_events` | Actor, action, target, timestamp, change metadata, correlation ID |
| `pricing_versions` | Provider/model pricing data and effective version |

### 10.2 Persistence rules

- Every tenant-owned record must be scoped and authorized.
- Use foreign keys and suitable indexes.
- Use UTC timestamps.
- Use transactions for policy publication and related audit metadata.
- Avoid storing raw prompts and outputs by default.
- Apply configurable retention policies to request metadata and audit records.
- Separate security audit events from high-volume diagnostic logs.
- Ensure request records can be correlated with provider attempts, usage, and guardrail events.
- Use migrations for all schema changes.

---

## 11. Observability and Auditability

### 11.1 Structured logging

Log structured fields such as:

- `timestamp`
- `level`
- `request_id`
- `organization_id` and `project_id` where appropriate and safe
- `client_id` (not the credential)
- `model_alias`
- `provider`
- `stage`
- `duration_ms`
- `status`
- `error_code`
- `policy_version`
- `guardrail_action`

Do not log API keys, authorization headers, provider secrets, unredacted PII, raw prompts, or full model outputs by default. Redaction must happen before data reaches log exporters.

### 11.2 Metrics

Required metrics include:

- Total requests and request outcomes.
- Request latency by stage and overall.
- Provider call latency and error rates.
- Retry and fallback counts.
- Input/output token usage.
- Estimated cost by provider/model/project.
- Guardrail decisions by stage/action/rule category.
- Rate-limit and budget rejections.
- Database and Redis dependency health.

Avoid high-cardinality labels such as request IDs, raw user prompts, and arbitrary client metadata in Prometheus metrics.

### 11.3 Tracing

Use OpenTelemetry spans for:

- Request reception.
- Authentication and authorization.
- Rate-limit and budget checks.
- Input guardrail evaluation.
- Route selection.
- Each provider attempt.
- Output guardrail evaluation.
- Persistence and usage accounting.

Traces must not include raw prompt content or secrets by default. Use sampling and retention settings appropriate to local resource constraints.

### 11.4 Audit events

Audit at least:

- API key creation, rotation, revocation.
- Policy creation, validation, publication, disablement, rollback.
- Provider/model configuration changes.
- Budget and quota changes.
- Admin access to sensitive reports where appropriate.
- Security-relevant request outcomes.

Audit records must be append-only at the application level. Do not allow ordinary administrative UI operations to silently edit or delete audit history.

---

## 12. Security and Threat Model

### 12.1 Assets to protect

- Provider credentials.
- API client credentials.
- Prompts and generated outputs.
- PII and other sensitive input data.
- Tenant/project configuration.
- Budgets and usage records.
- Guardrail policy definitions.
- Audit records and traces.

### 12.2 Threats and required mitigations

| Threat | Required mitigation |
|---|---|
| Unauthorized API access | API key authentication, revocation, scopes, rate limits |
| Cross-tenant data access | Server-side tenant scope checks, negative authorization tests |
| Prompt injection | Layered detectors, explicit policy decisions, no unrestricted tools |
| Sensitive data leakage | PII inspection, output guardrails, safe logging defaults |
| Provider key leakage | Secret configuration, redaction, no client exposure |
| Resource exhaustion | Body limits, token limits, deadlines, quotas, concurrency controls |
| Retry amplification | Bounded retries, jitter, deadlines, circuit breaker where implemented |
| Policy bypass | Immutable policy snapshots, precedence rules, central pipeline |
| Malicious provider response | Output validation, length limits, safe error handling |
| Audit tampering | Append-only application behavior, restricted access, retention controls |
| Budget race conditions | Atomic reservations/counters and concurrency tests |
| Dependency compromise | Dependency pinning, automated vulnerability checks where feasible |

### 12.3 Security requirements

- Validate all external input.
- Treat prompts and model outputs as untrusted data.
- Never execute model output as code or a shell command.
- Do not permit arbitrary provider URLs from clients.
- Apply timeouts to all network operations.
- Restrict CORS to configured origins if a browser UI is introduced.
- Use secure defaults for production-like configuration.
- Keep sensitive values out of exception responses.
- Document known limitations and the threat model.
- Test negative authorization paths, not only successful access.

---

## 13. Non-Functional Requirements

The initial project is a single-node portfolio deployment, but the code should preserve reasonable production-oriented boundaries.

### 13.1 Performance

Initial targets to validate by measurement:

- Deterministic gateway overhead: target p95 below 50 ms under a documented local test profile, excluding model-provider latency.
- Input/output guardrail execution time measured independently.
- No unbounded synchronous blocking on the event loop.
- Explicit concurrency limits for provider calls.
- Request deadlines propagated across routing and provider attempts.

These are goals, not claims. Document hardware, workload, sample size, and test method.

### 13.2 Reliability

- Every external provider call has a timeout.
- Retries are bounded.
- Dependency failures return controlled error responses.
- Health and readiness endpoints are distinct.
- A provider outage must not crash the whole API process.
- Persistence and usage-accounting failures must have documented behavior.
- No request may bypass mandatory guardrails because a detector or dependency failed.

### 13.3 Availability and failure policy

For mandatory security controls, define whether failure results in block, safe fallback, or service error. The default must be **fail closed** when the system cannot evaluate a mandatory policy. A policy may explicitly permit a different behavior only if that behavior is documented and approved.

For non-security optional enrichment, graceful degradation may be allowed.

### 13.4 Maintainability

- Use type hints and explicit interfaces.
- Keep HTTP routes thin.
- Keep provider-specific behavior inside adapters.
- Keep policy evaluation independent of HTTP and database frameworks where practical.
- Use configuration objects, not scattered environment lookups.
- Add docstrings for public interfaces and complex policy logic.
- Enforce formatting, linting, and type checks in CI.

### 13.5 Portability

The application must run locally with Docker Compose and support a test mode using mock providers. No real API credential should be necessary to run unit tests or the core integration suite.

---

## 14. Repository Structure

```text
securellm-gateway/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── dependencies.py
│   │   └── v1/
│   │       ├── chat.py
│   │       ├── models.py
│   │       ├── usage.py
│   │       └── health.py
│   ├── admin/
│   │   ├── policies.py
│   │   ├── providers.py
│   │   ├── clients.py
│   │   └── audit.py
│   ├── core/
│   │   ├── config.py
│   │   ├── auth.py
│   │   ├── authorization.py
│   │   ├── errors.py
│   │   └── request_context.py
│   ├── gateway/
│   │   ├── orchestrator.py
│   │   ├── router.py
│   │   ├── retries.py
│   │   ├── circuit_breaker.py
│   │   └── budgets.py
│   ├── providers/
│   │   ├── base.py
│   │   ├── litellm_adapter.py
│   │   ├── provider_a.py
│   │   ├── provider_b.py
│   │   └── mock.py
│   ├── guardrails/
│   │   ├── contracts.py
│   │   ├── engine.py
│   │   ├── policy_resolver.py
│   │   ├── input_pipeline.py
│   │   ├── output_pipeline.py
│   │   └── detectors/
│   │       ├── base.py
│   │       ├── pii.py
│   │       ├── injection.py
│   │       ├── content_policy.py
│   │       └── schema_validation.py
│   ├── usage/
│   │   ├── token_usage.py
│   │   ├── pricing.py
│   │   └── accounting.py
│   ├── persistence/
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── repositories/
│   │   └── migrations/
│   ├── rate_limit/
│   │   └── redis_limiter.py
│   ├── observability/
│   │   ├── logging.py
│   │   ├── metrics.py
│   │   ├── tracing.py
│   │   └── audit.py
│   └── schemas/
│       ├── requests.py
│       ├── responses.py
│       ├── policies.py
│       └── errors.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   ├── contract/
│   └── load/
├── configs/
│   ├── policies/
│   └── pricing/
├── deploy/
│   ├── prometheus/
│   └── grafana/
├── docs/
│   ├── architecture.md
│   ├── threat-model.md
│   ├── api-examples.md
│   └── benchmark-methodology.md
├── .github/workflows/ci.yml
├── .env.example
├── Dockerfile
├── compose.yaml
├── alembic.ini
├── pyproject.toml
└── README.md
```

This is the target structure, not a requirement to create empty files up front. Add modules when their corresponding milestone is implemented. Avoid duplicate provider implementations if a single adapter library covers the chosen providers adequately.

---

## 15. Testing and Acceptance Criteria

Testing is a release requirement, not a final polishing activity. Use mocks for deterministic unit tests and reserve live provider calls for optional smoke tests.

### 15.1 Test layers

1. **Unit tests:** Guardrail detectors, policy aggregation, routing, pricing, retries, auth helpers.
2. **Integration tests:** API + database + Redis + mocked provider.
3. **Contract tests:** Public schemas, error response formats, provider adapter normalization.
4. **Security tests:** Prompt injection corpus, PII, tenant isolation, credential leakage, policy bypass.
5. **Resilience tests:** Provider timeout, rate limit, malformed provider response, database/Redis outage.
6. **Load tests:** Concurrency, p50/p95 latency, throughput, resource consumption.
7. **Optional smoke tests:** Small number of calls to real providers, disabled by default in CI.

### 15.2 Required acceptance matrix

| Scenario | Expected result |
|---|---|
| Valid request | Normalized successful response |
| Missing/invalid API key | `401`; no provider call |
| Authenticated but unauthorized admin action | `403`; no mutation |
| Oversized request | Rejected before provider call |
| Rate limit exceeded | `429`; no provider call |
| Input guardrail blocks | Safe error; no provider call |
| PII configured for redaction | Provider receives redacted content; raw content is not logged |
| Output guardrail blocks | Unsafe output is not returned |
| Output schema invalid | Bounded repair if configured, otherwise controlled failure |
| Primary provider transient timeout | Bounded retry and eligible fallback |
| All providers unavailable | Controlled upstream error |
| Provider returns malformed data | Normalization failure; no raw stack trace exposed |
| Tenant A requests Tenant B usage | Access denied |
| Revoked key is used | `401`; no provider call |
| Policy published during a request | Current request retains original policy snapshot |
| Two concurrent requests approach budget | No unaccounted overspend beyond documented reservation semantics |
| Audit persistence fails | Documented fail-safe behavior; no silent claim of audit success |
| Secrets appear in provider exception | Secrets are not present in client response/logs |
| Benign text resembles an injection | Expected policy outcome; false positive measured |

### 15.3 Guardrail evaluation corpus

Maintain a version-controlled synthetic corpus with:

- Benign ordinary prompts.
- PII examples for each supported entity.
- Prompt-injection attempts.
- Benign security-related discussion.
- Content-policy edge cases.
- Output-leakage examples.
- Malformed structured output.
- Unicode and unusual whitespace cases.

Each case should specify expected action, expected stage, and relevant rule category. Track false-positive and false-negative rates for the tested corpus. Do not state that passing the corpus guarantees security.

### 15.4 CI requirements

On every pull request:

1. Format check.
2. Lint.
3. Type check for configured modules.
4. Unit tests.
5. Integration tests with disposable/mock dependencies.
6. Security regression tests.
7. Build container image.
8. Dependency vulnerability checks where available.

CI must not require production credentials. Fail the build on required test failures.

---

## 16. Delivery Roadmap

Target duration: approximately six weeks at 6–8 hours per week. Adjust based on actual availability; prioritize a complete vertical slice over superficial breadth.

### Phase 1 — Foundation and first request

**Scope**
- Project scaffolding, configuration, logging, FastAPI setup.
- Request/response schemas.
- Mock provider and one real provider adapter.
- Health endpoints and basic chat endpoint.

**Exit criteria**
- A request succeeds through the complete API.
- Tests run without external credentials using the mock provider.
- OpenAPI docs are available.

### Phase 2 — Routing and resilience

**Scope**
- Second provider adapter or alternate model route.
- Logical aliases.
- Provider error normalization.
- Timeouts, bounded retries, fallback.
- Attempt metadata.

**Exit criteria**
- A simulated provider failure produces a bounded, observable fallback.
- Non-retryable errors are not retried.
- No request can choose an arbitrary provider URL.

### Phase 3 — Guardrails

**Scope**
- Guardrail contracts and policy engine.
- Input/output pipelines.
- PII detection and redaction.
- Injection signals and content rules.
- Output/schema validation.
- Versioned policy configuration.

**Exit criteria**
- Input blocks happen before provider invocation.
- Output blocks prevent unsafe content from reaching the client.
- Policy decisions are deterministic for deterministic detectors and include version metadata.

### Phase 4 — Identity, quotas, persistence

**Scope**
- API client keys and revocation.
- Role/permission checks.
- Tenant/project model.
- PostgreSQL persistence and migrations.
- Redis rate limits.
- Budget checks and usage records.

**Exit criteria**
- Cross-tenant access tests pass.
- Rate limits work across multiple application instances or an appropriate integration simulation.
- Usage records link to request and provider attempts.

### Phase 5 — Observability and hardening

**Scope**
- Metrics and traces.
- Audit event handling.
- Dashboard.
- Security corpus and load tests.
- Failure-mode review.

**Exit criteria**
- A reviewer can trace a request through gateway, guardrails, and provider.
- Dashboard shows latency, errors, cost estimates, and policy actions.
- Security limitations and failure behavior are documented.

### Phase 6 — Packaging and portfolio presentation

**Scope**
- Docker Compose deployment.
- CI pipeline.
- README and API examples.
- Architecture diagram and threat model.
- Reproducible demo script and measured benchmarks.

**Exit criteria**
- A reviewer can clone, configure, launch, and test the project from documented steps.
- No secret is committed.
- All published performance/security claims are supported by reproducible measurements.

---

## 17. Definition of Done

The product is complete for the initial portfolio release only when:

- [ ] A documented local deployment starts successfully.
- [ ] The unified API works with at least one real provider and a deterministic mock.
- [ ] Two provider routes or a provider plus tested fallback are implemented.
- [ ] Input and output guardrails are integrated into the request lifecycle.
- [ ] Policies are versioned and auditable.
- [ ] Authentication, revocation, and tenant isolation are tested.
- [ ] Rate limits and usage accounting are implemented.
- [ ] Retries, deadlines, and fallback are bounded.
- [ ] Structured logs, metrics, and traces are available.
- [ ] Unit, integration, security, and contract tests run in CI.
- [ ] Benchmark methodology and measured results are documented.
- [ ] README includes architecture, setup, API examples, limitations, and demo scenarios.
- [ ] Secrets and sensitive data are excluded from source control and logs by default.

---

## 18. Demo Requirements

The final demonstration must show actual system behavior rather than only a successful prompt completion.

### Demo A — Multi-provider routing
Send a request through a logical alias. Show the selected provider, model, usage, latency, and estimated cost.

### Demo B — Guardrail enforcement
Submit benign and suspicious inputs. Show the decision, policy version, safe reason code, and whether the provider was called.

### Demo C — Output inspection
Use a deterministic mock provider to return synthetic PII or invalid structured output. Demonstrate redaction or rejection before the client receives the response.

### Demo D — Failure recovery
Simulate a timeout on the primary provider. Show bounded retry/fallback and the associated trace.

### Demo E — Client quotas
Send requests from two synthetic clients. Demonstrate independent rate limits, usage records, and authorization isolation.

### Demo F — Policy versioning
Publish a new policy version, verify the new behavior, and roll back to the previous version. Show the audit trail.

A small Streamlit dashboard, Swagger UI, and `curl` examples are sufficient; a large frontend is not required.

---

## 19. Documentation and Developer Experience

The repository must include:

- `README.md`: overview, features, architecture, setup, configuration, tests, demo.
- `docs/architecture.md`: component responsibilities, request sequence, key invariants.
- `docs/threat-model.md`: assets, trust boundaries, threats, mitigations, limitations.
- `docs/api-examples.md`: requests, responses, errors, authentication.
- `docs/benchmark-methodology.md`: environment, workload, sample size, metrics, results.
- `.env.example`: placeholder values only.
- A sample policy configuration with comments.
- A sample pricing configuration with explicit version and effective date.
- A troubleshooting guide for common startup and provider errors.

Document all unsupported features, particularly streaming, tool calls, provider-specific multimodal inputs, and exact spend guarantees.

---

## 20. Risks, Trade-offs, and Open Decisions

| Risk / decision | Required approach |
|---|---|
| Prompt-injection detection is imperfect | Layered controls, policy tuning, corpus-based evaluation, clear limitations |
| Provider APIs differ | Stable internal contract, adapter tests, explicit unsupported-feature errors |
| Exact spend cannot always be known before generation | Reservation/reconciliation, estimates, documented overage semantics |
| Guardrail latency may grow | Measure stages independently; configure detector budgets and deadlines |
| Redis/database outage can weaken controls | Define fail-closed/fail-open behavior by control; test failures explicitly |
| Logs can contain sensitive data | Data minimization, redaction, access control, retention policy |
| Too much scope for a portfolio project | Implement required vertical slice first; defer optional circuit breaker/UI refinements |
| Provider fallback can violate data policy | Enforce provider allowlists and data-handling constraints on every candidate |
| Policy changes can create inconsistent requests | Immutable version snapshots and atomic publication |
| Streaming complicates output guardrails | Exclude streaming from initial release unless incremental safety behavior is fully specified |

### Explicit initial assumptions

- The first release supports non-streaming text chat.
- At least one real provider is supported; a mock provider is mandatory for deterministic tests.
- A second provider or compatible alternate route is implemented for routing/fallback demonstrations.
- Redis and PostgreSQL are available in the Docker Compose environment.
- External provider credentials are optional for unit and core integration tests.
- Tool calling and arbitrary agent execution are disabled.
- Costs are estimates based on recorded usage and versioned pricing configuration.
- The first release targets a single deployment environment, not multi-region high availability.

---

## 21. Final Engineering Directive

Build SecureLLM Gateway as a cohesive platform, not as a proxy with unrelated security checks attached afterward.

The request lifecycle must have a single orchestration path. Guardrails must be reusable, independently testable modules. Provider adapters must normalize vendor differences. Policies must be versioned and auditable. Tenant boundaries must be enforced server-side. Reliability behavior must be bounded and measurable. Sensitive data must not be exposed through logs, errors, or traces.

**Priority order:**

1. Correct request lifecycle and stable API contract.
2. Mandatory input/output guardrails.
3. Authentication and tenant isolation.
4. Provider routing, deadlines, retries, and safe fallback.
5. Usage accounting, budgets, and rate limits.
6. Observability, auditability, and security regression tests.
7. Deployment polish, dashboards, and portfolio presentation.

Do not optimize for the number of features. Optimize for a system whose behavior can be explained, tested, observed, and reproduced.

**The final acceptance test is simple:** a developer should be able to clone the repository, launch the platform, send a request, observe a policy decision, simulate a provider failure, inspect usage and traces, and reproduce the documented test results without needing undocumented steps.
