from dataclasses import dataclass
from typing import Protocol

from app.schemas import Message


@dataclass(frozen=True)
class ProviderResult:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


class Provider(Protocol):
    name: str

    async def complete(
        self,
        messages: list[Message],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        timeout_s: float,
    ) -> ProviderResult:
        """Return a completion or raise ProviderTimeoutError / ProviderUpstreamError."""
        ...
