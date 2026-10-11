import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_CANARY = "CANARY-SECRET-0000"  # synthetic secret used to prove output checking is active


class AliasTarget(BaseModel):
    provider: str
    model: str
    enabled: bool = True


class ModelPricing(BaseModel):
    """USD per million tokens. Used only for an *estimated* cost, never for billing."""

    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)


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

    # Auth, rate limiting, persistence
    gateway_api_keys: SecretStr = SecretStr("")  # comma-separated list of accepted keys
    rate_limit_per_minute: int = Field(30, gt=0)
    database_url: str = "sqlite:///./gateway.db"
    # Optional: {"<provider model id>": {"input_per_mtok": 4.0, "output_per_mtok": 20.0}}
    pricing_json: dict[str, ModelPricing] = Field(default_factory=dict)

    # Request limits
    max_request_bytes: int = Field(32768, gt=0)
    max_messages: int = Field(50, gt=0)
    max_message_chars: int = Field(8000, gt=0)

    # Guardrails
    pii_redaction_enabled: bool = True
    injection_check_enabled: bool = True
    extra_input_block_patterns: list[str] = Field(default_factory=list)
    output_canary: str | None = DEFAULT_CANARY
    output_block_patterns: list[str] = Field(default_factory=list)

    # Anthropic (real provider). Credentials come from the environment only.
    anthropic_api_key: SecretStr | None = None
    anthropic_default_model: str = "claude-opus-5-5"
    # Thinking depth/cost control; None omits it (needed for models without effort support).
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = "low"

    @property
    def api_keys(self) -> list[str]:
        return [k.strip() for k in self.gateway_api_keys.get_secret_value().split(",") if k.strip()]

    @field_validator("extra_input_block_patterns", "output_block_patterns")
    @classmethod
    def _patterns_compile(cls, patterns: list[str]) -> list[str]:
        for p in patterns:
            try:
                re.compile(p)
            except re.error:
                raise ValueError("invalid regular expression in pattern list") from None
        return patterns

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
