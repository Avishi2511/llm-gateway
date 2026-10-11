from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RequestLog(Base):
    """One row per authenticated request. Holds metadata only: there are deliberately
    no columns for prompt text, completion text, matched values or raw API keys."""

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # naive UTC
    key_id: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    model_alias: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    duration_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    guardrail_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    guardrail_checks: Mapped[str | None] = mapped_column(String(256), nullable=True)  # comma-joined ids
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
