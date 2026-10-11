import anthropic
import httpx2 as httpx
import pytest

from app.errors import (
    InvalidRequestError,
    ProviderTimeoutError,
    ProviderUpstreamError,
    UnsupportedFeatureError,
)
from app.providers.anthropic_provider import AnthropicProvider
from app.schemas import Message

REQ = httpx.Request("POST", "https://example.invalid/v1/messages")


class FakeBlock:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class FakeResponse:
    def __init__(self, blocks, stop_reason="end_turn", usage=None):
        self.content, self.stop_reason, self.usage = blocks, stop_reason, usage


class FakeUsage:
    input_tokens = 7
    output_tokens = 3


class FakeMessages:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeClient:
    def __init__(self, outcome):
        self.messages = FakeMessages(outcome)


def provider(outcome, **kw):
    client = FakeClient(outcome)
    return AnthropicProvider(client=client, **kw), client


def msgs(*pairs):
    return [Message(role=r, content=c) for r, c in pairs]


async def call(p, messages, temperature=None):
    return await p.complete(messages, "claude-test", temperature, 256, 5.0)


async def test_success_maps_text_usage_and_finish_reason():
    resp = FakeResponse([FakeBlock("thinking"), FakeBlock("text", "Hi "), FakeBlock("text", "there")], usage=FakeUsage())
    p, client = provider(resp)
    result = await call(p, msgs(("user", "Hello")))
    assert result.content == "Hi there"  # non-text blocks ignored
    assert (result.input_tokens, result.output_tokens, result.finish_reason) == (7, 3, "end_turn")
    sent = client.messages.calls[0]
    assert sent["model"] == "claude-test" and sent["max_tokens"] == 256 and sent["timeout"] == 5.0
    assert sent["output_config"] == {"effort": "low"}


async def test_missing_usage_stays_none():
    p, _ = provider(FakeResponse([FakeBlock("text", "x")], usage=None))
    result = await call(p, msgs(("user", "Hello")))
    assert result.input_tokens is None and result.output_tokens is None


async def test_system_messages_move_to_system_param():
    p, client = provider(FakeResponse([FakeBlock("text", "ok")]))
    await call(p, msgs(("system", "Be brief."), ("user", "Hello"), ("system", "Be kind.")))
    sent = client.messages.calls[0]
    assert sent["system"] == "Be brief.\n\nBe kind."
    assert sent["messages"] == [{"role": "user", "content": "Hello"}]


async def test_effort_can_be_omitted():
    p, client = provider(FakeResponse([FakeBlock("text", "ok")]), effort=None)
    await call(p, msgs(("user", "Hello")))
    assert "output_config" not in client.messages.calls[0]


async def test_temperature_rejected_explicitly_without_calling_sdk():
    p, client = provider(FakeResponse([FakeBlock("text", "ok")]))
    with pytest.raises(UnsupportedFeatureError):
        await call(p, msgs(("user", "Hello")), temperature=0.5)
    assert client.messages.calls == []


@pytest.mark.parametrize("pairs", [[("system", "only system")], [("assistant", "first"), ("user", "x")]])
async def test_invalid_message_order_rejected_without_calling_sdk(pairs):
    p, client = provider(FakeResponse([FakeBlock("text", "ok")]))
    with pytest.raises(InvalidRequestError):
        await call(p, msgs(*pairs))
    assert client.messages.calls == []


@pytest.mark.parametrize(
    "exc,expected",
    [
        (anthropic.APITimeoutError(request=REQ), ProviderTimeoutError),
        (anthropic.APIConnectionError(request=REQ), ProviderUpstreamError),
        (
            anthropic.RateLimitError("rate limited SECRET-DETAIL", response=httpx.Response(429, request=REQ), body=None),
            ProviderUpstreamError,
        ),
        (
            anthropic.InternalServerError("boom SECRET-DETAIL", response=httpx.Response(500, request=REQ), body=None),
            ProviderUpstreamError,
        ),
        (
            anthropic.AuthenticationError("bad key SECRET-DETAIL", response=httpx.Response(401, request=REQ), body=None),
            ProviderUpstreamError,
        ),
    ],
)
async def test_sdk_errors_are_normalized_and_do_not_leak(exc, expected):
    p, _ = provider(exc)
    with pytest.raises(expected) as info:
        await call(p, msgs(("user", "Hello")))
    assert "SECRET-DETAIL" not in str(info.value)
    assert info.value.__cause__ is None  # original SDK error not chained into responses
