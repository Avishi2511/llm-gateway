import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_client(**overrides) -> TestClient:
    settings = Settings(_env_file=None, **overrides)
    # raise_server_exceptions=False so the 500 handler is exercised like a real server
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture
def client() -> TestClient:
    return make_client()


@pytest.fixture
def valid_body() -> dict:
    return {"model": "default", "messages": [{"role": "user", "content": "Hello"}]}
