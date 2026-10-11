import asyncio

import pytest

from app.config import Settings
from app.providers.base import ProviderResult
from tests.api.test_chat_basic import URL, assert_error
from tests.conftest import make_client


class SlowProvider:
    name = "mock"

    def __init__(self, delay):
        self.delay, self.finished = delay, False

    async def complete(self, messages, model, temperature, max_tokens, timeout_s):
        await asyncio.sleep(self.delay)
        self.finished = True
        return ProviderResult(content="late")


def test_wall_clock_timeout_enforced_on_slow_provider(valid_body):
    client = make_client(provider_timeout_seconds=0.05)
    slow = SlowProvider(delay=2)
    client.app.state.providers["mock"] = slow
    client.app.state.service.providers["mock"] = slow
    resp = client.post(URL, json=valid_body)
    assert_error(resp, "PROVIDER_TIMEOUT", 504)
    assert "late" not in resp.text and not slow.finished


@pytest.mark.parametrize("field", ["provider", "api_key", "provider_model", "base_url"])
def test_client_cannot_select_provider_or_credentials(client, valid_body, field):
    valid_body[field] = "anything"
    assert_error(client.post(URL, json=valid_body), "INVALID_REQUEST", 422)
    assert client.app.state.providers["mock"].call_count == 0


def test_disabled_alias_behaves_as_unknown(valid_body):
    client = make_client(
        model_aliases={
            "default": {"provider": "mock", "model": "m"},
            "off": {"provider": "mock", "model": "m", "enabled": False},
        }
    )
    valid_body["model"] = "off"
    assert_error(client.post(URL, json=valid_body), "UNKNOWN_MODEL", 400)
    assert client.app.state.providers["mock"].call_count == 0


def test_alias_maps_to_configured_provider_model(valid_body):
    client = make_client(model_aliases={"fast": {"provider": "mock", "model": "mock-fast"}})
    seen = []
    mock = client.app.state.providers["mock"]
    original = mock.complete

    async def spy(messages, model, temperature, max_tokens, timeout_s):
        seen.append(model)
        return await original(messages, model, temperature, max_tokens, timeout_s)

    mock.complete = spy
    valid_body["model"] = "fast"
    assert client.post(URL, json=valid_body).status_code == 200
    assert seen == ["mock-fast"]  # client sent the alias, provider got the configured model id


def test_real_mode_requires_api_key():
    from app.main import create_app

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        create_app(Settings(_env_file=None, provider_mode="real"))


def test_real_mode_builds_anthropic_provider_without_network():
    from app.main import create_app

    app = create_app(Settings(_env_file=None, provider_mode="real", anthropic_api_key="test-key"))
    assert app.state.providers["anthropic"].name == "anthropic"
    assert app.state.settings.model_aliases["default"].provider == "anthropic"
    assert app.state.settings.model_aliases["default"].model == "claude-opus-5-5"


def test_api_key_never_appears_in_settings_repr():
    s = Settings(_env_file=None, provider_mode="real", anthropic_api_key="super-secret-123")
    assert "super-secret-123" not in repr(s) and "super-secret-123" not in str(s)
