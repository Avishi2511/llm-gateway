from app.config import Settings
from app.errors import ProviderUpstreamError, UnsupportedFeatureError
from app.gateway.aliases import resolve_alias
from app.providers.base import Provider
from app.schemas import AssistantMessage, ChatRequest, ChatResponse, Usage


def ensure_supported(req: ChatRequest) -> None:
    """Explicitly reject unsupported features instead of silently ignoring them."""
    if req.stream:
        raise UnsupportedFeatureError("Streaming is not supported.")
    if any(v is not None for v in (req.tools, req.tool_choice, req.functions, req.function_call)):
        raise UnsupportedFeatureError("Tool and function calling are not supported.")
    if any(not isinstance(m.content, str) for m in req.messages):
        raise UnsupportedFeatureError("Only plain text message content is supported.")


class GatewayService:
    """Request orchestration. No FastAPI imports: testable without a server."""

    def __init__(self, settings: Settings, providers: dict[str, Provider]):
        self.settings = settings
        self.providers = providers

    async def handle_chat(self, req: ChatRequest, request_id: str, key_id: str | None = None) -> ChatResponse:
        ensure_supported(req)
        resolved = resolve_alias(self.settings, req.model)

        provider = self.providers.get(resolved.provider_name)
        if provider is None:
            raise ProviderUpstreamError()

        max_tokens = req.max_tokens
        cap = self.settings.max_output_tokens_cap
        if max_tokens is None or max_tokens > cap:
            max_tokens = cap

        result = await provider.complete(
            messages=req.messages,
            model=resolved.provider_model,
            temperature=req.temperature,
            max_tokens=max_tokens,
            timeout_s=self.settings.provider_timeout_seconds,
        )

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
        )
