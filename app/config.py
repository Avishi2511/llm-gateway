from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AliasTarget(BaseModel):
    provider: str
    model: str
    enabled: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    provider_mode: Literal["mock", "real"] = "mock"
    mock_behavior: Literal["success", "fail", "timeout", "unsafe"] = "success"
    model_aliases: dict[str, AliasTarget] = Field(
        default_factory=lambda: {"default": AliasTarget(provider="mock", model="mock-1")}
    )
    provider_timeout_seconds: float = Field(30.0, gt=0)
    max_output_tokens_cap: int = Field(1024, gt=0)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _aliases_not_empty(self) -> "Settings":
        if not self.model_aliases:
            raise ValueError("MODEL_ALIASES must define at least one alias")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
