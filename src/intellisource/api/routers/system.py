"""System health and metrics API router (AC-T099-4: backed by real checkers)."""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import (
    APIRouter,  # noqa: I001 — keep top-of-block predictability
    Depends,
    Request,
)
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.api.routers.llm import compute_llm_stats
from intellisource.api.schemas.common import OperationResult
from intellisource.api.schemas.observability import HealthResponse
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["system"])


def _format_prometheus(
    metrics_collector: Any, suppress_empty_labeled: set[str] | None = None
) -> str:
    """Render MetricsCollector counters / gauges / histograms as Prom text.

    Output follows ``# HELP`` + ``# TYPE`` + sample-line shape so a Prometheus
    scraper can consume the per-process exposition directly. Per-process
    aggregation is by design; cross-process roll-up belongs in the
    deployment-level Prometheus aggregator (out of scope here).

    ``suppress_empty_labeled`` names labeled-counter families that are also
    rendered from the shared store (pushes_total). When the local series for
    such a family is empty, its ``# TYPE`` line is dropped here so the shared
    store can own it — otherwise the merged exposition would carry a duplicate
    ``# TYPE`` line and Prometheus would reject the whole scrape.
    """
    if metrics_collector is None:
        return ""
    suppress = suppress_empty_labeled or set()

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
        if not series and name in suppress:
            # The shared store owns this family's exposition; skipping the empty
            # local TYPE line avoids a duplicate that would break the scrape.
            continue
        lines.append(f"# TYPE {name} counter")
        for label_key, value in sorted(series.items()):
            label_str = ",".join(
                f'{k}="{v}"'
                for pair in label_key.split(",")
                for k, v in [pair.split("=", 1)]
            )
            lines.append(f"{name}{{{label_str}}} {value}")
    return "\n".join(lines) + ("\n" if lines else "")


@router.get("/health", response_model=HealthResponse)
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
    missing = getattr(request.app.state, "missing_config", None)
    if missing:
        payload["missing_config"] = missing
    return payload


@router.get("/metrics")
async def metrics(request: Request) -> PlainTextResponse:
    """Return Prometheus exposition text for app.state.metrics_collector."""
    return metrics_response(request)


def metrics_response(request: Request) -> PlainTextResponse:
    """Build Prometheus text from app.state.metrics_collector + shared store.

    The local collector covers API-process families (``http_*`` / ``llm_*`` /
    ``llm_circuit_open`` / health); worker-process families (``celery_*`` and
    ``pushes_total``, both recorded in the prefork worker) are merged in from
    the shared Redis store so one scrape of ``/api/v1/metrics`` surfaces every
    advertised family across processes.
    """
    from intellisource.observability.shared_metrics import (
        get_shared_metric_store,
        render_shared_metrics_text,
    )

    store = getattr(request.app.state, "shared_metrics", None)
    if store is None:
        store = get_shared_metric_store()
    shared_entries = store.read_all()
    shared_names = {entry["name"] for entry in shared_entries}

    collector = getattr(request.app.state, "metrics_collector", None)
    # Drop the empty local TYPE line for any family the shared store also owns
    # (pushes_total) so the merged output carries a single TYPE per family.
    text = _format_prometheus(collector, suppress_empty_labeled=shared_names)
    text += render_shared_metrics_text(shared_entries)
    return PlainTextResponse(content=text, media_type="text/plain; version=0.0.4")


@router.get("/llm-stats", response_model=OperationResult)
async def system_llm_stats(
    period: str = "day",
    model: str | None = None,
    call_type: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    """LLM usage statistics under the system namespace.

    Alias of ``GET /llm/stats`` — delegates to the same ``compute_llm_stats``
    implementation so the two endpoints stay behaviourally identical.
    """
    return await compute_llm_stats(
        session, period=period, model=model, call_type=call_type
    )
