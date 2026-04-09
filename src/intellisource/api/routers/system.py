"""System health and metrics API router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["system"])


# ---------------------------------------------------------------------------
# Stub functions (tests patch these)
# ---------------------------------------------------------------------------


async def check_health() -> dict[str, Any]:
    """Return system health status. Tests patch this function."""
    return {"status": "healthy"}  # pragma: no cover


async def get_metrics() -> str:
    """Return Prometheus-format metrics text. Tests patch this function."""
    return ""  # pragma: no cover


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health")
async def health() -> dict[str, Any]:
    return await check_health()


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    text = await get_metrics()
    return PlainTextResponse(content=text, media_type="text/plain")
