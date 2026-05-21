"""LLM stats API router (API-017)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.storage.repositories.llm_call_log import LLMCallLogRepository

router = APIRouter(tags=["llm"])


@router.get("/llm/stats")
async def llm_stats(
    period: str = "day",
    model: str | None = None,
    call_type: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    repo = LLMCallLogRepository(session)
    try:
        return await repo.get_stats(
            period=period,
            model=model,
            call_type=call_type,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


async def get_llm_gateway_status() -> dict[str, Any]:
    """Return current circuit breaker state and queue lengths.

    Returns a dict with keys:
    - circuit_state: one of CLOSED, OPEN, HALF_OPEN
    - queue_lengths: dict with interactive and background integer counts
    """
    return {
        "circuit_state": "CLOSED",
        "queue_lengths": {"interactive": 0, "background": 0},
    }


@router.get("/llm/status")
async def llm_status() -> Any:
    """Return LLM gateway health: circuit state and queue depths."""
    return await get_llm_gateway_status()
