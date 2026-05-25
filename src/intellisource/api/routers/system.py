"""System health and metrics API router (AC-T099-4: backed by real checkers)."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from fastapi import (
    APIRouter,  # noqa: I001 — keep top-of-block predictability
    Depends,
    Request,
)
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.storage.repositories.llm_call_log import LLMCallLogRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


def _format_prometheus(metrics_collector: Any) -> str:
    """Render MetricsCollector counters / gauges / histograms as Prom text.

    Output follows ``# HELP`` + ``# TYPE`` + sample-line shape so a Prometheus
    scraper can consume the per-process exposition directly. Per-process
    aggregation is by design; cross-process roll-up belongs in the
    deployment-level Prometheus aggregator (out of scope for T-099).
    """
    if metrics_collector is None:
        return ""

    lines: list[str] = []
    for name, desc, value in metrics_collector.iter_counters():
        lines.append(f"# HELP {name} {desc}")
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name} {value}")
    for name, desc, value in metrics_collector.iter_gauges():
        lines.append(f"# HELP {name} {desc}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {value}")
    for name, desc, values in metrics_collector.iter_histograms():
        lines.append(f"# HELP {name} {desc}")
        lines.append(f"# TYPE {name} histogram")
        lines.append(f"{name}_count {len(values)}")
        lines.append(f"{name}_sum {sum(values)}")
    for name, desc, series in metrics_collector.iter_labeled_gauges():
        lines.append(f"# HELP {name} {desc}")
        lines.append(f"# TYPE {name} gauge")
        for label_key, value in sorted(series.items()):
            label_str = ",".join(
                f'{k}="{v}"'
                for pair in label_key.split(",")
                for k, v in [pair.split("=", 1)]
            )
            lines.append(f"{name}{{{label_str}}} {int(value)}")
    for name, series in metrics_collector.iter_labeled_counters():
        lines.append(f"# TYPE {name} counter")
        for label_key, value in sorted(series.items()):
            label_str = ",".join(
                f'{k}="{v}"'
                for pair in label_key.split(",")
                for k, v in [pair.split("=", 1)]
            )
            lines.append(f"{name}{{{label_str}}} {value}")
    return "\n".join(lines) + ("\n" if lines else "")


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Return real DB/Redis/Celery health via app.state.health_checker."""
    return await health_payload(request)


async def health_payload(request: Request) -> dict[str, Any]:
    """Build a health payload from app.state.health_checker."""
    checker = getattr(request.app.state, "health_checker", None)
    if checker is None:
        return {
            "status": "unhealthy",
            "version": getattr(request.app, "version", "unknown"),
            "uptime_seconds": 0.0,
            "checks": {"meta": "checker_missing"},
        }

    try:
        result = await checker.check_health()
    except Exception:
        logger.exception("health_checker raised")
        return {"status": "unhealthy", "checks": {"meta": "checker_failed"}}

    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        payload: dict[str, Any] = dataclasses.asdict(result)
    else:
        payload = dict(result)
    timestamp = payload.get("timestamp")
    if timestamp is not None and hasattr(timestamp, "isoformat"):
        payload["timestamp"] = timestamp.isoformat()
    return payload


@router.get("/metrics")
async def metrics(request: Request) -> PlainTextResponse:
    """Return Prometheus exposition text for app.state.metrics_collector."""
    return metrics_response(request)


def metrics_response(request: Request) -> PlainTextResponse:
    """Build Prometheus text from app.state.metrics_collector."""
    collector = getattr(request.app.state, "metrics_collector", None)
    text = _format_prometheus(collector)
    return PlainTextResponse(content=text, media_type="text/plain; version=0.0.4")


@router.get("/llm-stats")
async def system_llm_stats(
    period: str = "day",
    model: str | None = None,
    call_type: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    """Return LLM usage statistics under the system namespace."""
    repo = LLMCallLogRepository(session)
    try:
        return await repo.get_stats(
            period=period,
            model=model,
            call_type=call_type,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
