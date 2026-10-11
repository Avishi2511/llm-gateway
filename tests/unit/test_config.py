import pytest
from pydantic import ValidationError

from app.config import Settings
from app.providers.registry import build_providers


def test_defaults_work_without_any_env():
    s = Settings(_env_file=None)
    assert s.provider_mode == "mock"
    assert "default" in s.model_aliases


def test_empty_aliases_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, model_aliases={})


def test_alias_with_unknown_provider_fails_fast():
    s = Settings(_env_file=None, model_aliases={"x": {"provider": "ghost", "model": "m"}})
    with pytest.raises(ValueError):
        build_providers(s)
