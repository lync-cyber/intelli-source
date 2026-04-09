"""LLM stats API router."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["llm"])


# ---------------------------------------------------------------------------
# Stub repository (no dedicated module yet)
# ---------------------------------------------------------------------------


class LLMCallLogRepository:
    """Stub LLM call log repository. Tests mock this class."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_stats(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        period: str = "day",
    ) -> dict[str, Any]:
        return {}  # pragma: no cover


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def get_session() -> AsyncIterator[AsyncSession]:
    """Placeholder DB session dependency."""
    yield None  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/llm/stats")
async def llm_stats(
    date_from: str | None = None,
    date_to: str | None = None,
    period: str = "day",
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    repo = LLMCallLogRepository(session)
    return await repo.get_stats(
        date_from=date_from,
        date_to=date_to,
        period=period,
    )
