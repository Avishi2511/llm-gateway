import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.config import Settings
from app.db.repo import UsageRepository
from app.errors import (
    GatewayError,
    InputBlockedError,
    OutputBlockedError,
    ProviderTimeoutError,
    ProviderUpstreamError,
    RequestTooLargeError,
    UnsupportedFeatureError,
)
from app.gateway.aliases import resolve_alias
from app.guardrails.input import InputGuardrails
from app.guardrails.output import OutputGuardrails
from app.guardrails.types import Action
from app.providers.base import Provider
from app.ratelimit import RateLimiter
from app.schemas import AssistantMessage, ChatRequest, ChatResponse, GuardrailSummary, Usage

logger = logging.getLogger("gateway.service")

# Error code -> usage status. Anything not listed (validation, unknown model, ...) is "invalid".
_STATUS_BY_CODE = {
    "INPUT_BLOCKED": "blocked_input",
    "OUTPUT_BLOCKED": "blocked_output",
    "PROVIDER_ERROR": "provider_error",
    "PROVIDER_TIMEOUT": "timeout",
    "RATE_LIMITED": "rate_limited",
    "INTERNAL_ERROR": "internal_error",
}


def ensure_supported(req: ChatRequest) -> None:
    """Explicitly reject unsupported features instead of silently ignoring them."""
    if req.stream:
        raise UnsupportedFeatureError("Streaming is not supported.")
    if any(v is not None for v in (req.tools, req.tool_choice, req.functions, req.function_call)):
        raise UnsupportedFeatureError("Tool and function calling are not supported.")
    if any(not isinstance(m.content, str) for m in req.messages):
        raise UnsupportedFeatureError("Only plain text message content is supported.")


def enforce_limits(req: ChatRequest, settings: Settings) -> None:
    if len(req.messages) > settings.max_messages:
        raise RequestTooLargeError()
    if any(len(m.content) > settings.max_message_chars for m in req.messages):
        raise RequestTooLargeError()


@dataclass
class _Outcome:
    """Safe metadata collected while handling one request. Never holds prompt or completion text."""

    alias: str | None = None
    status: str = "success"
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    guardrail_action: str | None = None
    guardrail_checks: list[str] = field(default_factory=list)


class GatewayService:
    """Request orchestration. No FastAPI imports: testable without a server."""

    def __init__(
        self,
        settings: Settings,
        providers: dict[str, Provider],
        input_guardrails: InputGuardrails | None = None,
        output_guardrails: OutputGuardrails | None = None,
        limiter: RateLimiter | None = None,
        repo: UsageRepository | None = None,
    ):
        self.settings = settings
        self.providers = providers
        self.limiter = limiter
        self.repo = repo
        self.input_guardrails = input_guardrails or InputGuardrails(
            redact_pii=settings.pii_redaction_enabled,
            injection_enabled=settings.injection_check_enabled,
            extra_block_patterns=settings.extra_input_block_patterns,
        )
        self.output_guardrails = output_guardrails or OutputGuardrails(
            canary=settings.output_canary,
            block_patterns=settings.output_block_patterns,
        )

    async def handle_chat(
        self,
        req: ChatRequest,
        request_id: str,
        key_id: str | None = None,
        started_at: float | None = None,
    ) -> ChatResponse:
        started = started_at if started_at is not None else time.perf_counter()
        # Only record the alias if it is configured: arbitrary client text never reaches the database.
        outcome = _Outcome(alias=req.model if req.model in self.settings.model_aliases else None)
        try:
            return await self._process(req, request_id, key_id, outcome)
        except GatewayError as exc:
            outcome.status = _STATUS_BY_CODE.get(exc.code, "invalid")
            outcome.error_code = exc.code
            raise
        except asyncio.CancelledError:
            outcome.status, outcome.error_code = "cancelled", None
            raise
        except Exception:
            outcome.status, outcome.error_code = "internal_error", "INTERNAL_ERROR"
            raise
        finally:
            self._record(request_id, key_id, started, outcome)

    def record_invalid(self, request_id: str, key_id: str | None, started_at: float) -> None:
        """Usage row for a request rejected by schema validation before reaching handle_chat."""
        self._record(request_id, key_id, started_at, _Outcome(status="invalid", error_code="INVALID_REQUEST"))

    def _record(self, request_id: str, key_id: str | None, started: float, o: _Outcome) -> None:
        if self.repo is None:
            return
        try:
            self.repo.record(
                request_id=request_id,
                key_id=key_id,
                model_alias=o.alias,
                status=o.status,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                input_tokens=o.input_tokens,
                output_tokens=o.output_tokens,
                estimated_cost=o.estimated_cost,
                guardrail_action=o.guardrail_action,
                guardrail_checks=o.guardrail_checks or None,
                error_code=o.error_code,
            )
        except Exception as exc:
            # A persistence problem must not change what the client receives.
            logger.error("usage_record_failed request_id=%s type=%s", request_id, type(exc).__name__)

    def _estimate_cost(self, provider_model: str, in_tokens: int | None, out_tokens: int | None) -> float | None:
        pricing = self.settings.pricing_json.get(provider_model)
        if pricing is None or in_tokens is None or out_tokens is None:
            return None  # never invent a cost
        return (in_tokens * pricing.input_per_mtok + out_tokens * pricing.output_per_mtok) / 1_000_000

    async def _process(self, req: ChatRequest, request_id: str, key_id: str | None, o: _Outcome) -> ChatResponse:
        if self.limiter is not None and key_id is not None:
            self.limiter.check(key_id)

        ensure_supported(req)
        enforce_limits(req, self.settings)
        resolved = resolve_alias(self.settings, req.model)

        provider = self.providers.get(resolved.provider_name)
        if provider is None:
            raise ProviderUpstreamError()

        # Input guardrails run before any provider call. Check ids only are logged, never content.
        decision = self.input_guardrails.check(req.messages)
        o.guardrail_action = decision.action.value
        o.guardrail_checks = decision.check_ids
        if decision.checks:
            logger.info("input_guardrail request_id=%s action=%s checks=%s",
                        request_id, decision.action.value, decision.check_ids)
        if decision.action is Action.BLOCK:
            raise InputBlockedError()
        messages = decision.messages if decision.messages is not None else req.messages

        max_tokens = req.max_tokens
        cap = self.settings.max_output_tokens_cap
        if max_tokens is None or max_tokens > cap:
            max_tokens = cap

        timeout = self.settings.provider_timeout_seconds
        try:
            # Wall-clock backstop on top of any SDK-level timeout.
            result = await asyncio.wait_for(
                provider.complete(
                    messages=messages,
                    model=resolved.provider_model,
                    temperature=req.temperature,
                    max_tokens=max_tokens,
                    timeout_s=timeout,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ProviderTimeoutError() from None

        o.input_tokens, o.output_tokens = result.input_tokens, result.output_tokens
        o.estimated_cost = self._estimate_cost(resolved.provider_model, result.input_tokens, result.output_tokens)

        # The only path to a ChatResponse is through this check: if it blocks or raises,
        # the generated content is dropped and never reaches the caller.
        out_decision = self.output_guardrails.check(result.content)
        if out_decision.action is Action.BLOCK:
            o.guardrail_action = Action.BLOCK.value
            o.guardrail_checks = out_decision.check_ids
            logger.info("output_guardrail request_id=%s action=block checks=%s",
                        request_id, out_decision.check_ids)
            raise OutputBlockedError()

        total = (
            result.input_tokens + result.output_tokens
            if result.input_tokens is not None and result.output_tokens is not None
            else None
        )
        return ChatResponse(
            request_id=request_id,
            model=req.model,
            message=AssistantMessage(content=result.content),
            usage=Usage(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=total,
            ),
            finish_reason=result.finish_reason,
            guardrails=GuardrailSummary(action=decision.action.value, checks=decision.check_ids),
        )
