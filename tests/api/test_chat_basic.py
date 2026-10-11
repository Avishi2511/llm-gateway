import pytest

from tests.conftest import make_client

URL = "/v1/chat/completions"


def assert_error(resp, code, status):
    assert resp.status_code == status
    err = resp.json()["error"]
    assert err["code"] == code
    assert err["request_id"].startswith("req_")
    assert err["request_id"] == resp.headers["X-Request-ID"]
    return err


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "provider_mode": "mock"}


def test_valid_request_returns_deterministic_mock_completion(client, valid_body):
    first = client.post(URL, json=valid_body)
    second = client.post(URL, json=valid_body)
    assert first.status_code == 200
    data = first.json()
    assert data["model"] == "default"
    assert data["message"] == {"role": "assistant", "content": "Mock reply to a 5-character message."}
    assert data["finish_reason"] == "stop"
    assert data["usage"]["total_tokens"] == data["usage"]["input_tokens"] + data["usage"]["output_tokens"]
    assert data["request_id"] == first.headers["X-Request-ID"]
    assert second.json()["message"] == data["message"]
    assert second.json()["request_id"] != data["request_id"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(messages=[{"role": "tool", "content": "x"}]),  # bad role
        lambda b: b.update(messages=[]),  # empty messages
        lambda b: b.update(messages=[{"role": "user", "content": "  "}]),  # blank content
        lambda b: b.update(unexpected="field"),  # extra field
        lambda b: b.update(temperature=5),  # out of range
        lambda b: b.pop("model"),  # missing model
    ],
)
def test_invalid_payload_rejected_before_provider(client, valid_body, mutate):
    mutate(valid_body)
    resp = client.post(URL, json=valid_body)
    assert_error(resp, "INVALID_REQUEST", 422)
    assert client.app.state.providers["mock"].call_count == 0


def test_validation_error_does_not_echo_submitted_values(client, valid_body):
    valid_body["messages"] = [{"role": "user", "content": "secret@example.com", "oops": "LEAKME"}]
    resp = client.post(URL, json=valid_body)
    assert "LEAKME" not in resp.text and "secret@example.com" not in resp.text


@pytest.mark.parametrize(
    "extra",
    [{"stream": True}, {"tools": [{"type": "function"}]}, {"functions": []}],
)
def test_unsupported_features_rejected_explicitly(client, valid_body, extra):
    valid_body.update(extra)
    assert_error(client.post(URL, json=valid_body), "UNSUPPORTED_FEATURE", 400)
    assert client.app.state.providers["mock"].call_count == 0


def test_multimodal_content_rejected(client, valid_body):
    valid_body["messages"] = [{"role": "user", "content": [{"type": "image_url"}]}]
    assert_error(client.post(URL, json=valid_body), "UNSUPPORTED_FEATURE", 400)


def test_stream_false_is_accepted(client, valid_body):
    valid_body["stream"] = False
    assert client.post(URL, json=valid_body).status_code == 200


def test_unknown_alias_rejected_without_provider_call(client, valid_body):
    valid_body["model"] = "nope"
    assert_error(client.post(URL, json=valid_body), "UNKNOWN_MODEL", 400)
    assert client.app.state.providers["mock"].call_count == 0


def test_max_tokens_clamped_to_server_cap(valid_body):
    client = make_client(max_output_tokens_cap=100)
    seen = []
    provider = client.app.state.providers["mock"]
    original = provider.complete

    async def spy(messages, model, temperature, max_tokens, timeout_s):
        seen.append(max_tokens)
        return await original(messages, model, temperature, max_tokens, timeout_s)

    provider.complete = spy
    valid_body["max_tokens"] = 99999
    assert client.post(URL, json=valid_body).status_code == 200
    assert seen == [100]


@pytest.mark.parametrize(
    "behavior,code,status",
    [("fail", "PROVIDER_ERROR", 502), ("timeout", "PROVIDER_TIMEOUT", 504)],
)
def test_provider_failures_are_normalized(valid_body, behavior, code, status):
    client = make_client(mock_behavior=behavior)
    assert_error(client.post(URL, json=valid_body), code, status)


def test_unexpected_exception_returns_safe_500(valid_body):
    client = make_client()

    async def boom(*args, **kwargs):
        raise RuntimeError("sensitive-detail-xyz")

    client.app.state.providers["mock"].complete = boom
    resp = client.post(URL, json=valid_body)
    err = assert_error(resp, "INTERNAL_ERROR", 500)
    assert "sensitive-detail-xyz" not in resp.text
    assert err["message"] == "An internal error occurred."


def test_unknown_route_uses_error_envelope(client):
    assert_error(client.get("/nope"), "NOT_FOUND", 404)
