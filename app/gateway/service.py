import asyncio
import logging

from app.config import Settings
from app.errors import (
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
from app.schemas import AssistantMessage, ChatRequest, ChatResponse, GuardrailSummary, Usage

logger = logging.getLogger("gateway.service")


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


class GatewayService:
    """Request orchestration. No FastAPI imports: testable without a server."""

    def __init__(
        self,
        settings: Settings,
        providers: dict[str, Provider],
        input_guardrails: InputGuardrails | None = None,
        output_guardrails: OutputGuardrails | None = None,
    ):
        self.settings = settings
        self.providers = providers
        self.input_guardrails = input_guardrails or InputGuardrails(
            redact_pii=settings.pii_redaction_enabled,
            injection_enabled=settings.injection_check_enabled,
            extra_block_patterns=settings.extra_input_block_patterns,
        )
        self.output_guardrails = output_guardrails or OutputGuardrails(
            canary=settings.output_canary,
            block_patterns=settings.output_block_patterns,
        )

    async def handle_chat(self, req: ChatRequest, request_id: str, key_id: str | None = None) -> ChatResponse:
        ensure_supported(req)
        enforce_limits(req, self.settings)
        resolved = resolve_alias(self.settings, req.model)

        provider = self.providers.get(resolved.provider_name)
        if provider is None:
            raise ProviderUpstreamError()

        # Input guardrails run before any provider call. Check ids only are logged, never content.
        decision = self.input_guardrails.check(req.messages)
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

        # The only path to a ChatResponse is through this check: if it blocks or raises,
        # the generated content is dropped and never reaches the caller.
        out_decision = self.output_guardrails.check(result.content)
        if out_decision.action is Action.BLOCK:
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
