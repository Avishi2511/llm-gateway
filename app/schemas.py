from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    # A list is accepted by the schema only so multimodal input can be rejected
    # with UNSUPPORTED_FEATURE instead of a generic validation error.
    content: str | list[Any]

    @field_validator("content")
    @classmethod
    def _non_empty_text(cls, v: str | list[Any]) -> str | list[Any]:
        if isinstance(v, str) and not v.strip():
            raise ValueError("content must not be empty")
        return v


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    messages: list[Message] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)

    # Accepted by the schema only to be explicitly rejected (never silently ignored).
    stream: bool | None = None
    tools: Any | None = None
    tool_choice: Any | None = None
    functions: Any | None = None
    function_call: Any | None = None


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class GuardrailSummary(BaseModel):
    action: Literal["allow", "redact", "block"] = "allow"
    checks: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    request_id: str
    model: str
    message: AssistantMessage
    usage: Usage
    finish_reason: str | None = None
    guardrails: GuardrailSummary = Field(default_factory=GuardrailSummary)


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class ModelInfo(BaseModel):
    id: str


class ModelList(BaseModel):
    data: list[ModelInfo]


class UsageRecord(BaseModel):
    request_id: str
    created_at: datetime
    model_alias: str | None
    status: str
    duration_ms: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: float | None = Field(description="Estimate in USD from configured pricing; not a billable amount.")
    guardrail_action: str | None
    guardrail_checks: list[str]
    error_code: str | None


class UsageList(BaseModel):
    data: list[UsageRecord]
