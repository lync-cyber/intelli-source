"""LLMCallLogRepository -- multi-dimensional aggregation for LLM call logs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.storage.models import LLMCallLog
from intellisource.storage.repositories.base import BaseRepository

_PERIOD_DELTAS: dict[str, timedelta] = {
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}


class LLMCallLogRepository(BaseRepository[LLMCallLog]):
    """Repository for LLMCallLog with aggregation helpers."""

    _model_class = LLMCallLog

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_stats(
        self,
        *,
        period: str = "day",
        model: str | None = None,
        call_type: str | None = None,
    ) -> dict[str, Any]:
        """Return aggregated LLM call statistics for the given filters."""
        delta = _PERIOD_DELTAS.get(period)
        if delta is None:
            valid = sorted(_PERIOD_DELTAS)
            raise ValueError(f"Unsupported period: '{period}'. Valid values: {valid}")

        now = datetime.now(timezone.utc)
        start = now - delta

        base_filters = [LLMCallLog.created_at >= start]
        if model is not None:
            base_filters.append(LLMCallLog.model == model)
        if call_type is not None:
            base_filters.append(LLMCallLog.call_type == call_type)

        global_stmt = select(
            func.count().label("total_calls"),
            func.coalesce(func.sum(LLMCallLog.input_tokens), 0).label(
                "total_input_tokens"
            ),
            func.coalesce(func.sum(LLMCallLog.output_tokens), 0).label(
                "total_output_tokens"
            ),
            func.coalesce(func.avg(LLMCallLog.latency_ms), 0.0).label("avg_latency_ms"),
        ).where(*base_filters)

        result = await self._session.execute(global_stmt)
        row = result.one()

        total_calls: int = row.total_calls
        total_input_tokens: int = row.total_input_tokens
        total_output_tokens: int = row.total_output_tokens
        avg_latency_ms: float = float(row.avg_latency_ms)

        by_model = await self._get_by_model(base_filters)
        by_date = await self._get_by_date(base_filters)

        return {
            "period": period,
            "total_calls": total_calls,
            "total_tokens": total_input_tokens + total_output_tokens,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "avg_latency_ms": avg_latency_ms,
            "by_model": by_model,
            "by_date": by_date,
        }

    async def _get_by_model(self, base_filters: list[Any]) -> list[dict[str, Any]]:
        error_expr = case(
            (LLMCallLog.status == "error", 1.0),
            else_=0.0,
        )
        stmt = (
            select(
                LLMCallLog.model,
                func.count().label("call_count"),
                func.coalesce(func.sum(LLMCallLog.input_tokens), 0).label(
                    "input_tokens"
                ),
                func.coalesce(func.sum(LLMCallLog.output_tokens), 0).label(
                    "output_tokens"
                ),
                func.avg(error_expr).label("error_rate"),
            )
            .where(*base_filters)
            .group_by(LLMCallLog.model)
        )

        result = await self._session.execute(stmt)
        rows = result.all()
        return [
            {
                "model": r.model,
                "call_count": r.call_count,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "error_rate": float(r.error_rate) if r.error_rate is not None else 0.0,
            }
            for r in rows
        ]

    async def _get_by_date(self, base_filters: list[Any]) -> list[dict[str, Any]]:
        date_expr = func.date(LLMCallLog.created_at)
        stmt = (
            select(
                date_expr.label("date"),
                func.count().label("call_count"),
                func.coalesce(
                    func.sum(LLMCallLog.input_tokens + LLMCallLog.output_tokens), 0
                ).label("total_tokens"),
            )
            .where(*base_filters)
            .group_by(date_expr)
            .order_by(date_expr)
        )

        result = await self._session.execute(stmt)
        rows = result.all()
        return [
            {
                "date": str(r.date),
                "call_count": r.call_count,
                "total_tokens": r.total_tokens,
            }
            for r in rows
        ]
