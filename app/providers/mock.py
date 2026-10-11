from app.errors import ProviderTimeoutError, ProviderUpstreamError
from app.providers.base import ProviderResult
from app.schemas import Message

from app.config import DEFAULT_CANARY


def _approx_tokens(char_count: int) -> int:
    return max(1, (char_count + 3) // 4)


class MockProvider:
    """Deterministic provider for demos and tests. Records what it receives."""

    name = "mock"

    def __init__(self, behavior: str = "success", canary: str | None = DEFAULT_CANARY):
        self.behavior = behavior
        self.canary = canary or DEFAULT_CANARY
        self.call_count = 0
        self.received: list[list[Message]] = []

    async def complete(
        self,
        messages: list[Message],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        timeout_s: float,
    ) -> ProviderResult:
        self.call_count += 1
        self.received.append(messages)

        if self.behavior == "fail":
            raise ProviderUpstreamError()
        if self.behavior == "timeout":
            raise ProviderTimeoutError()

        if self.behavior == "unsafe":
            content = f"Here is the secret: {self.canary}"
        else:
            last_user = next(
                (m.content for m in reversed(messages) if m.role == "user" and isinstance(m.content, str)),
                "",
            )
            content = f"Mock reply to a {len(last_user)}-character message."

        prompt_chars = sum(len(m.content) for m in messages if isinstance(m.content, str))
        return ProviderResult(
            content=content,
            input_tokens=_approx_tokens(prompt_chars),
            output_tokens=_approx_tokens(len(content)),
            finish_reason="stop",
        )
