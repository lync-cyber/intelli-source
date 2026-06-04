"""LLM stats API router (API-017)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session, require_api_key
from intellisource.api.errors import error_json
from intellisource.api.schemas.common import OperationResult
from intellisource.api.schemas.observability import LLMStatusResponse
from intellisource.observability.logging import get_logger
from intellisource.storage.repositories.llm_call_log import LLMCallLogRepository

logger = get_logger(__name__)

router = APIRouter(tags=["llm"])


async def compute_llm_stats(
    session: AsyncSession,
    *,
    period: str = "day",
    model: str | None = None,
    call_type: str | None = None,
) -> Any:
    """Single source of truth for LLM usage stats.

    Shared by ``GET /llm/stats`` and the ``GET /system/llm-stats`` alias so the
    two endpoints can never diverge. Returns the stats payload, or a 400
    JSONResponse when ``period`` (or another argument) is invalid.
    """
    repo = LLMCallLogRepository(session)
    try:
        return await repo.get_stats(period=period, model=model, call_type=call_type)
    except ValueError as exc:
        return error_json(400, str(exc))


@router.get("/llm/stats", response_model=OperationResult)
async def llm_stats(
    period: str = "day",
    model: str | None = None,
    call_type: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    return await compute_llm_stats(
        session, period=period, model=model, call_type=call_type
    )


async def get_llm_gateway_status(request: Request) -> dict[str, Any]:
    """Return current circuit breaker state and queue lengths.

    Reads LLMGateway from request.app.state.llm_gateway when available.
    Returns circuit_state="UNKNOWN" with a runtime warning when the gateway
    is not injected (e.g. during testing or misconfigured deployments).

    Returns a dict with keys:
    - circuit_state: one of CLOSED, OPEN, HALF_OPEN, UNKNOWN
    - queue_lengths: dict with interactive and background integer counts
    """
    gateway = getattr(request.app.state, "llm_gateway", None)
    if gateway is None:
        logger.warning(
            "llm_gateway not found in app.state; returning UNKNOWN circuit state"
        )
        return {
            "circuit_state": "UNKNOWN",
            "queue_lengths": {"interactive": 0, "background": 0},
        }

    circuit_state = "UNKNOWN"
    if gateway.circuit_breaker is not None:
        state = await gateway.circuit_breaker.get_state()
        circuit_state = state.value

    interactive = 0
    background = 0
    if gateway._priority_queue is not None:
        interactive = gateway._priority_queue.interactive_queue_size()
        background = gateway._priority_queue.background_queue_size()

    return {
        "circuit_state": circuit_state,
        "queue_lengths": {"interactive": interactive, "background": background},
    }


@router.get("/llm/status", response_model=LLMStatusResponse)
async def llm_status(
    request: Request,
    _: str = Depends(require_api_key),
) -> Any:
    """Return LLM gateway health: circuit state and queue depths."""
    return await get_llm_gateway_status(request)
