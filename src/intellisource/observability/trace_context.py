"""Cross-process trace_id ContextVar shared by the API and Celery workers.

Lives in :mod:`intellisource.observability` (rather than ``api/middleware``)
so the worker process can import it without dragging the FastAPI stack.
The ASGI ``TracingMiddleware`` sets the var on every HTTP request; downstream
``send_task`` calls forward it via the Celery message ``headers`` argument,
and the worker ``task_prerun`` signal handler restores it before the task
body runs so structured logs share a stable correlation id across
process boundaries.
"""

from __future__ import annotations

import contextvars

TRACE_HEADER_KEY: str = "trace_id"

trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)


def current_trace_id() -> str:
    """Return the trace_id bound to the current async context, or ""."""
    return trace_id_ctx.get()


def set_trace_id(value: str) -> contextvars.Token[str]:
    """Bind *value* to the current async context; return reset token."""
    return trace_id_ctx.set(value or "")


def reset_trace_id(token: contextvars.Token[str]) -> None:
    """Pop the trace_id binding previously installed by :func:`set_trace_id`."""
    trace_id_ctx.reset(token)
