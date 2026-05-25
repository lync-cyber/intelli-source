"""Celery task dispatch facade — enforces trace_id injection into message headers."""

from __future__ import annotations

import uuid
from typing import Any

from celery import Celery
from celery.result import AsyncResult

from intellisource.observability.trace_context import TRACE_HEADER_KEY, current_trace_id
from intellisource.scheduler.celery_app import celery_app


def send_task_with_trace(
    name: str,
    args: tuple[Any, ...] | list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    *,
    queue: str | None = None,
    headers: dict[str, Any] | None = None,
    celery_instance: Celery | None = None,
    **options: Any,
) -> AsyncResult:
    """Unified Celery dispatch entry point; injects current trace_id into headers.

    Why: scattered send_task calls risk silently dropping the trace chain.
    This is the single allowed call site for celery_app.send_task.

    Pass *celery_instance* to override the module-level singleton (e.g. from
    ``request.app.state.celery_app`` in ASGI handlers).
    """
    app = celery_instance if celery_instance is not None else celery_app
    merged_headers: dict[str, Any] = dict(headers or {})
    trace_id = current_trace_id() or str(uuid.uuid4())
    merged_headers.setdefault(TRACE_HEADER_KEY, trace_id)
    return app.send_task(
        name,
        args=args,
        kwargs=kwargs,
        queue=queue,
        headers=merged_headers,
        **options,
    )
