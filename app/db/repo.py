from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import RequestLog


class UsageRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def record(
        self,
        *,
        request_id: str,
        key_id: str | None,
        model_alias: str | None,
        status: str,
        duration_ms: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        estimated_cost: float | None = None,
        guardrail_action: str | None = None,
        guardrail_checks: list[str] | None = None,
        error_code: str | None = None,
    ) -> None:
        row = RequestLog(
            request_id=request_id,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            key_id=key_id,
            model_alias=model_alias,
            status=status,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            guardrail_action=guardrail_action,
            guardrail_checks=",".join(guardrail_checks) if guardrail_checks else None,
            error_code=error_code,
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()

    def recent(self, key_id: str, limit: int) -> list[dict[str, Any]]:
        """Newest-first records belonging to one key."""
        stmt = (
            select(RequestLog)
            .where(RequestLog.key_id == key_id)
            .order_by(RequestLog.id.desc())
            .limit(limit)
        )
        with self._session_factory() as session:
            rows = session.scalars(stmt).all()
        return [
            {
                "request_id": r.request_id,
                "created_at": r.created_at.replace(tzinfo=timezone.utc),
                "model_alias": r.model_alias,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "estimated_cost": r.estimated_cost,
                "guardrail_action": r.guardrail_action,
                "guardrail_checks": r.guardrail_checks.split(",") if r.guardrail_checks else [],
                "error_code": r.error_code,
            }
            for r in rows
        ]
