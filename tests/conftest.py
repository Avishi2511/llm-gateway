import os

import pytest
from fastapi.testclient import TestClient

# Set before any Settings object is built so tests never touch a real database file or real keys.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["GATEWAY_API_KEYS"] = "test-key-1,test-key-2"

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

KEY1, KEY2 = "test-key-1", "test-key-2"


def make_client(key: str | None = KEY1, **overrides) -> TestClient:
    """Test client with a valid Authorization header by default (pass key=None for none)."""
    settings = Settings(_env_file=None, **overrides)
    # raise_server_exceptions=False so the 500 handler is exercised like a real server
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    if key:
        client.headers["Authorization"] = f"Bearer {key}"
    return client


@pytest.fixture
def client() -> TestClient:
    return make_client()


@pytest.fixture
def valid_body() -> dict:
    return {"model": "default", "messages": [{"role": "user", "content": "Hello"}]}
