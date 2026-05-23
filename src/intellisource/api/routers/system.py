"""System health and metrics API router (AC-T099-4: backed by real checkers)."""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import (
    APIRouter,  # noqa: I001 — keep top-of-block predictability
    Request,
)
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["system"])


def _format_prometheus(metrics_collector: Any) -> str:
    """Render a MetricsCollector's counters / gauges / histograms as Prom text.

    Output follows the standard ``# HELP`` + ``# TYPE`` + sample-line shape so
    a Prometheus scraper can consume the per-process exposition directly.
    Per-process aggregation is by design; cross-process roll-up belongs in the
    deployment-level Prometheus aggregator (out of scope for T-099).
    """
    if metrics_collector is None:
        return ""

    lines: list[str] = []

    counters = getattr(metrics_collector, "_counters", {})
    counter_desc = getattr(metrics_collector, "_counter_descriptions", {})
    for name, value in counters.items():
        desc = counter_desc.get(name, name)
        lines.append(f"# HELP {name} {desc}")
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name} {value}")

    gauges = getattr(metrics_collector, "_gauges", {})
    gauge_desc = getattr(metrics_collector, "_gauge_descriptions", {})
    for name, value in gauges.items():
        desc = gauge_desc.get(name, name)
        lines.append(f"# HELP {name} {desc}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {value}")

    histograms = getattr(metrics_collector, "_histograms", {})
    histo_desc = getattr(metrics_collector, "_histogram_descriptions", {})
    for name, values in histograms.items():
        desc = histo_desc.get(name, name)
        lines.append(f"# HELP {name} {desc}")
        lines.append(f"# TYPE {name} histogram")
        lines.append(f"{name}_count {len(values)}")
        lines.append(f"{name}_sum {sum(values)}")

    return "\n".join(lines) + ("\n" if lines else "")


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Return real DB/Redis/Celery health via app.state.health_checker."""
    checker = getattr(request.app.state, "health_checker", None)
    if checker is None:
        return {"status": "healthy", "checks": {}}

    result = await checker.check_health()
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
    collector = getattr(request.app.state, "metrics_collector", None)
    text = _format_prometheus(collector)
    return PlainTextResponse(content=text, media_type="text/plain")
