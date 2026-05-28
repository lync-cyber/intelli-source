"""Celery worker signal handlers — propagate trace_id + record metrics (F-22/F-23).

Importing this module subscribes the handlers idempotently; the import path is
``from intellisource.scheduler import signals``. The handlers are designed to
be safe inside test workers (no broker round-trip, no DB I/O).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import structlog
from celery.signals import task_failure, task_postrun, task_prerun

from intellisource.observability.metrics import MetricsCollector
from intellisource.observability.trace_context import (
    TRACE_HEADER_KEY,
    reset_trace_id,
    set_trace_id,
)

logger = logging.getLogger(__name__)

_TRACE_TOKEN_ATTR: str = "_intellisource_trace_token"
_START_TIME_ATTR: str = "_intellisource_started_at"

_METRIC_TASKS_TOTAL = "celery_tasks_total"
_METRIC_TASK_FAILURES = "celery_task_failures_total"
_METRIC_TASK_DURATION = "celery_task_duration_seconds"


def _register_metrics(mc: MetricsCollector) -> None:
    """Idempotently register the Celery-side metrics on *mc*."""
    if _METRIC_TASKS_TOTAL not in mc._counters:
        mc.register_counter(
            _METRIC_TASKS_TOTAL,
            "Total Celery tasks executed (any status)",
        )
    if _METRIC_TASK_FAILURES not in mc._counters:
        mc.register_counter(
            _METRIC_TASK_FAILURES,
            "Total Celery tasks ended in failure",
        )
    if _METRIC_TASK_DURATION not in mc._histograms:
        mc.register_histogram(
            _METRIC_TASK_DURATION,
            "Wall-clock duration (seconds) of Celery task execution",
        )


@task_prerun.connect  # type: ignore[untyped-decorator]
def _on_task_prerun(sender: Any = None, task_id: str = "", **_: Any) -> None:
    """Restore trace_id contextvar from message headers; start wall-clock timer."""
    task = sender
    if task is None:
        return
    headers: dict[str, Any] = {}
    try:
        request = task.request  # Celery Context object
        raw_headers = getattr(request, "headers", None) or {}
        if isinstance(raw_headers, dict):
            headers = raw_headers
    except Exception:  # noqa: BLE001 — defensive: never raise out of a signal
        headers = {}
    incoming = str(headers.get(TRACE_HEADER_KEY) or "")
    token = set_trace_id(incoming)
    try:
        structlog.contextvars.bind_contextvars(trace_id=incoming or "-")
    except Exception:  # noqa: BLE001 — defensive: never raise out of a signal
        pass
    setattr(task.request, _TRACE_TOKEN_ATTR, token)
    setattr(task.request, _START_TIME_ATTR, time.monotonic())


@task_postrun.connect  # type: ignore[untyped-decorator]
def _on_task_postrun(
    sender: Any = None,
    task_id: str = "",
    state: str = "",
    **_: Any,
) -> None:
    """Observe duration, increment success/total counters, reset trace_id."""
    task = sender
    if task is None:
        return
    try:
        mc = MetricsCollector.get_instance()
        _register_metrics(mc)
        mc.increment_counter(_METRIC_TASKS_TOTAL)
        start = getattr(task.request, _START_TIME_ATTR, None)
        if isinstance(start, float):
            mc.observe_histogram(_METRIC_TASK_DURATION, time.monotonic() - start)
    except Exception:  # noqa: BLE001 — signal handlers must never raise
        logger.exception("failed to record celery task metrics")

    try:
        structlog.contextvars.unbind_contextvars("trace_id")
    except Exception:  # noqa: BLE001 — never raise out of a signal
        pass

    token = getattr(task.request, _TRACE_TOKEN_ATTR, None)
    if token is not None:
        try:
            reset_trace_id(token)
        except (ValueError, LookupError):
            # Reset can race across workers in test pools — non-fatal.
            pass


@task_failure.connect  # type: ignore[untyped-decorator]
def _on_task_failure(sender: Any = None, **_: Any) -> None:
    """Increment the failure counter; the postrun handler still fires after this."""
    try:
        mc = MetricsCollector.get_instance()
        _register_metrics(mc)
        mc.increment_counter(_METRIC_TASK_FAILURES)
    except Exception:  # noqa: BLE001
        logger.exception("failed to record celery task failure metric")
