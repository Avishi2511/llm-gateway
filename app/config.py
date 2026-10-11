from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AliasTarget(BaseModel):
    provider: str
    model: str
    enabled: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    provider_mode: Literal["mock", "real"] = "mock"
    mock_behavior: Literal["success", "fail", "timeout", "unsafe"] = "success"
    # If unset, the default alias is derived from provider_mode (see validator below).
    model_aliases: dict[str, AliasTarget] = Field(
        default_factory=lambda: {"default": AliasTarget(provider="mock", model="mock-1")}
    )
    provider_timeout_seconds: float = Field(30.0, gt=0)
    provider_max_retries: int = Field(0, ge=0, le=1)
    max_output_tokens_cap: int = Field(1024, gt=0)
    log_level: str = "INFO"

    # Anthropic (real provider). Credentials come from the environment only.
    anthropic_api_key: SecretStr | None = None
    anthropic_default_model: str = "claude-opus-5-5"
    # Thinking depth/cost control; None omits it (needed for models without effort support).
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = "low"

    @model_validator(mode="after")
    def _finalize_aliases(self) -> "Settings":
        if "model_aliases" not in self.model_fields_set and self.provider_mode == "real":
            self.model_aliases = {
                "default": AliasTarget(provider="anthropic", model=self.anthropic_default_model)
            }
        if not self.model_aliases:
            raise ValueError("MODEL_ALIASES must define at least one alias")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
