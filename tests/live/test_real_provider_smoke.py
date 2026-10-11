"""Manual smoke test against the real Anthropic API (costs a few tokens).

Run with:  RUN_LIVE=1 ANTHROPIC_API_KEY=... pytest tests/live
Skipped by default so the normal suite needs no credentials.
"""
import os

import pytest

from app.config import Settings
from tests.conftest import make_client

pytestmark = pytest.mark.skipif(
    not (os.getenv("RUN_LIVE") and os.getenv("ANTHROPIC_API_KEY")),
    reason="set RUN_LIVE=1 and ANTHROPIC_API_KEY to run live tests",
)


def test_real_completion_through_gateway():
    client = make_client(provider_mode="real", anthropic_api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "default", "messages": [{"role": "user", "content": "Reply with the word: pong"}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"]["content"].strip()
