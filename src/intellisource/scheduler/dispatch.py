"""Celery task dispatch facade — enforces trace_id injection into message headers."""

from __future__ import annotations

import uuid
from typing import Any

from celery import Celery
from celery.result import AsyncResult
from kombu.exceptions import OperationalError as KombuOperationalError

from intellisource.observability.trace_context import TRACE_HEADER_KEY, current_trace_id
from intellisource.scheduler.celery_app import celery_app


class BrokerUnavailableError(RuntimeError):
    """Raised when task dispatch cannot reach the Celery broker.

    Carries the originating connection error as ``__cause__`` so callers can map
    it to a fast 503 instead of blocking on kombu reconnect.
    """


# Connection-level failures that mean "broker unreachable" — wrapped into
# BrokerUnavailableError so the publish path fails fast. builtin ConnectionError
# + OSError cover socket-level refusals/timeouts; redis.exceptions.ConnectionError
# is NOT a builtin-ConnectionError subclass (it derives from RedisError), so it
# is added explicitly when the redis transport is installed.
_BROKER_CONNECTION_ERRORS: tuple[type[BaseException], ...] = (
    KombuOperationalError,
    ConnectionError,
    OSError,
)
try:
    from redis.exceptions import ConnectionError as _RedisConnectionError

    _BROKER_CONNECTION_ERRORS = (*_BROKER_CONNECTION_ERRORS, _RedisConnectionError)
except ImportError:  # redis transport not installed — kombu errors still covered
    pass


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
    # retry=False so a dead broker fails fast instead of looping through the
    # publish retry policy; combined with broker_transport_options socket
    # timeouts the call raises within seconds. Connection-level failures are
    # wrapped so callers map them to 503 rather than 500/hang.
    options.setdefault("retry", False)
    try:
        return app.send_task(
            name,
            args=args,
            kwargs=kwargs,
            queue=queue,
            headers=merged_headers,
            **options,
        )
    except _BROKER_CONNECTION_ERRORS as exc:
        raise BrokerUnavailableError(str(exc)) from exc
    except RuntimeError as exc:
        # Safety net for Celery's redis result-backend reconnect exhaustion,
        # which surfaces as a bare RuntimeError ("Retry limit exceeded while
        # trying to reconnect to the Celery result store backend") rather than a
        # connection error. The fast-fail backend config should normally raise a
        # connection error first; this catches the residual case so dispatch
        # never blocks the caller behind an unreachable store.
        if "result store backend" in str(exc) or "reconnect" in str(exc):
            raise BrokerUnavailableError(str(exc)) from exc
        raise
