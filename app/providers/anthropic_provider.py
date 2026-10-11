import logging
from typing import Any

import anthropic

from app.errors import (
    InvalidRequestError,
    ProviderTimeoutError,
    ProviderUpstreamError,
    UnsupportedFeatureError,
)
from app.providers.base import ProviderResult
from app.schemas import Message

logger = logging.getLogger("gateway.provider.anthropic")


class AnthropicProvider:
    """Adapter around the official Anthropic SDK.

    SDK exceptions never escape: they are mapped to ProviderTimeoutError /
    ProviderUpstreamError with fixed messages. Only the exception type and HTTP
    status are logged (SDK messages can echo request content).
    """

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        effort: str | None = "low",
        max_retries: int = 0,
        client: Any | None = None,
    ):
        self.effort = effort
        # `client` is injectable so tests can fake the SDK without network access.
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=max_retries)

    async def complete(
        self,
        messages: list[Message],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        timeout_s: float,
    ) -> ProviderResult:
        if temperature is not None:
            # Current Claude models and the SDK do not accept a sampling temperature;
            # reject explicitly rather than silently ignoring it.
            raise UnsupportedFeatureError("The temperature setting is not supported by this model.")

        system_parts = [m.content for m in messages if m.role == "system" and isinstance(m.content, str)]
        chat = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system" and isinstance(m.content, str)
        ]
        if not chat or chat[0]["role"] != "user":
            raise InvalidRequestError("Messages must contain a user message before any assistant message.")

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or 1024,
            "messages": chat,
            "timeout": timeout_s,
        }
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}

        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.APITimeoutError as exc:  # before APIConnectionError: it is a subclass
            logger.warning("provider_timeout type=%s", type(exc).__name__)
            raise ProviderTimeoutError() from None
        except anthropic.APIStatusError as exc:
            logger.warning("provider_error type=%s status=%s", type(exc).__name__, exc.status_code)
            raise ProviderUpstreamError() from None
        except anthropic.APIError as exc:  # connection errors and other SDK failures
            logger.warning("provider_error type=%s", type(exc).__name__)
            raise ProviderUpstreamError() from None

        text = "".join(block.text for block in response.content if block.type == "text")
        usage = getattr(response, "usage", None)
        return ProviderResult(
            content=text,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            finish_reason=response.stop_reason,
        )
