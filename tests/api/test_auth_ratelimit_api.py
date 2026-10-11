import pytest

from app.ratelimit import RateLimiter
from tests.api.test_chat_basic import URL, assert_error
from tests.conftest import KEY1, KEY2, make_client


def provider(client):
    return client.app.state.providers["mock"]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic test-key-1"}, {"Authorization": "test-key-1"}],
)
def test_bad_or_missing_key_returns_401_without_provider_call(valid_body, headers):
    client = make_client(key=None)
    resp = client.post(URL, json=valid_body, headers=headers)
    err = assert_error(resp, "UNAUTHORIZED", 401)
    assert err["message"] == "Missing or invalid API key."
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    assert provider(client).call_count == 0


def test_auth_checked_before_validation():
    client = make_client(key=None)
    assert_error(client.post(URL, json={"junk": 1}), "UNAUTHORIZED", 401)  # not a 422 leaking the schema


def test_any_configured_key_works(valid_body):
    for key in (KEY1, KEY2):
        assert make_client(key=key).post(URL, json=valid_body).status_code == 200


def test_health_is_public_but_models_and_usage_need_a_key():
    client = make_client(key=None)
    assert client.get("/health").status_code == 200
    assert_error(client.get("/v1/models"), "UNAUTHORIZED", 401)
    assert_error(client.get("/v1/usage"), "UNAUTHORIZED", 401)


def test_startup_requires_at_least_one_key(monkeypatch):
    from app.config import Settings
    from app.main import create_app

    with pytest.raises(ValueError, match="GATEWAY_API_KEYS"):
        create_app(Settings(_env_file=None, gateway_api_keys=" , "))


def test_rate_limit_returns_429_with_retry_after(valid_body):
    client = make_client(rate_limit_per_minute=2)
    assert client.post(URL, json=valid_body).status_code == 200
    assert client.post(URL, json=valid_body).status_code == 200
    resp = client.post(URL, json=valid_body)
    assert_error(resp, "RATE_LIMITED", 429)
    assert int(resp.headers["Retry-After"]) >= 1
    assert provider(client).call_count == 2  # the limited request never reached the provider


def test_rate_limit_is_per_key_and_resets(valid_body):
    client = make_client(rate_limit_per_minute=1)
    now = [0.0]
    limiter = RateLimiter(1, 60, clock=lambda: now[0])
    client.app.state.service.limiter = limiter

    assert client.post(URL, json=valid_body).status_code == 200
    assert_error(client.post(URL, json=valid_body), "RATE_LIMITED", 429)
    other = client.post(URL, json=valid_body, headers={"Authorization": f"Bearer {KEY2}"})
    assert other.status_code == 200  # second key has its own budget
    now[0] += 61
    assert client.post(URL, json=valid_body).status_code == 200  # window reset


def test_unauthenticated_requests_do_not_consume_a_keys_budget(valid_body):
    client = make_client(rate_limit_per_minute=1)
    for _ in range(5):
        client.post(URL, json=valid_body, headers={"Authorization": "Bearer nope"})
    assert client.post(URL, json=valid_body).status_code == 200


def test_rate_limit_is_checked_after_validation(valid_body):
    client = make_client(rate_limit_per_minute=1)
    assert client.post(URL, json={"bad": 1}).status_code == 422  # invalid requests aren't counted
    assert client.post(URL, json=valid_body).status_code == 200


def test_api_keys_never_appear_in_logs_or_responses(caplog, valid_body):
    import logging

    caplog.set_level(logging.DEBUG)
    client = make_client(rate_limit_per_minute=1)
    responses = [
        client.post(URL, json=valid_body),
        client.post(URL, json=valid_body),  # 429
        client.post(URL, json=valid_body, headers={"Authorization": "Bearer wrong-secret-key"}),  # 401
        client.get("/v1/usage"),
    ]
    blob = caplog.text + "".join(r.text + str(dict(r.headers)) for r in responses)
    assert KEY1 not in blob and "wrong-secret-key" not in blob
    assert "auth_failed" in caplog.text
