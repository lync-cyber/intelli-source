"""Cost tracking for LLM calls (T-021)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.storage.models import LLMCallLog

_PERIOD_DELTAS: dict[str, timedelta] = {
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}

_ZERO_STATS: dict[str, int] = {
    "total_calls": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
}


@dataclass
class LLMCallRecord:
    """Data transfer object for an LLM call."""

    model: str
    provider: str
    call_type: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    input_length: int
    output_length: int
    status: str
    retry_attempt: int | None = None
    error_message: str | None = None


class CostTracker:
    """Tracks LLM call costs and provides aggregated statistics."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def log_call(self, record: LLMCallRecord) -> None:
        """Persist an LLM call record to the database."""
        orm_obj = LLMCallLog(
            model=record.model,
            provider=record.provider,
            call_type=record.call_type,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            latency_ms=record.latency_ms,
            input_length=record.input_length,
            output_length=record.output_length,
            status=record.status,
            retry_attempt=record.retry_attempt,
            error_message=record.error_message,
        )
        self._session.add(orm_obj)
        await self._session.commit()

    async def get_stats(
        self,
        period: str,
        model: str | None = None,
        call_type: str | None = None,
    ) -> dict[str, Any]:
        """Get aggregated statistics for the given period."""
        delta = _PERIOD_DELTAS.get(period)
        if delta is None:
            valid = sorted(_PERIOD_DELTAS)
            raise ValueError(f"Unsupported period: '{period}'. Valid values: {valid}")

        now = datetime.now(timezone.utc)
        start = now - delta

        stmt = select(
            func.count().label("total_calls"),
            func.coalesce(func.sum(LLMCallLog.input_tokens), 0).label(
                "total_input_tokens"
            ),
            func.coalesce(func.sum(LLMCallLog.output_tokens), 0).label(
                "total_output_tokens"
            ),
        ).where(LLMCallLog.created_at >= start)

        if model is not None:
            stmt = stmt.where(LLMCallLog.model == model)
        if call_type is not None:
            stmt = stmt.where(LLMCallLog.call_type == call_type)

        result = await self._session.execute(stmt)
        rows = result.all()

        if not rows:
            return {
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
            }

        row = rows[0]
        return {
            "total_calls": row.total_calls,
            "total_input_tokens": row.total_input_tokens,
            "total_output_tokens": row.total_output_tokens,
        }
