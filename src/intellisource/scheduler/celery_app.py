"""Module-level Celery application singleton for IntelliSource."""

from __future__ import annotations

import os

from celery import Celery
from kombu import Queue

from intellisource.scheduler.queues import PRIORITY_QUEUES, TRIGGER_TYPE_QUEUES


def _resolve_url(*env_keys: str, default: str) -> str:
    """Return the first non-empty value from *env_keys*, or *default*."""
    for key in env_keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

celery_app = Celery(
    "intellisource",
    broker=_resolve_url("IS_CELERY_BROKER_URL", "IS_REDIS_URL", default="memory://"),
    backend=_resolve_url(
        "IS_CELERY_RESULT_BACKEND", "IS_REDIS_URL", default="cache+memory://"
    ),
)

celery_app.conf.broker_connection_retry_on_startup = False

# Keep the TraceIdFormatter installed by setup_logging() in worker_process_init:
# Celery's default root-logger hijack otherwise replaces it with its own
# formatter, dropping trace_id= from every worker log line.
celery_app.conf.worker_hijack_root_logger = False
# Do not let Celery swap sys.stderr for its LoggingProxy: that proxy is installed
# before worker_process_init runs, so setup_logging()'s StreamHandler(sys.stderr)
# would bind to the proxy and its trace_id= lines would be swallowed. With this
# off, our handler writes to the real stderr captured by the container.
celery_app.conf.worker_redirect_stdouts = False

# B-059 fast-fail: a dead Redis must not hang a publish from /tasks/collect.
# Two distinct connections are involved on send — the broker (publish) AND the
# redis result store (Celery touches the backend during dispatch). BOTH must be
# bounded, or the slower one dominates (the result backend otherwise retries
# ~100s before raising). These are set at construction so the cached backend
# picks them up; post-init conf changes do not apply. Worker-side reconnection
# still applies per attempt — these only cap each attempt's duration.
celery_app.conf.broker_transport_options = {
    "socket_connect_timeout": 5,
    "socket_timeout": 5,
}
# Redis result-backend connection bounds + no reconnect retry loop, so a down
# backend surfaces a connection error fast instead of the ~100s "Retry limit
# exceeded while trying to reconnect to the Celery result store backend".
celery_app.conf.redis_socket_connect_timeout = 5
celery_app.conf.redis_socket_timeout = 5
celery_app.conf.redis_retry_on_timeout = False
celery_app.conf.result_backend_always_retry = False
celery_app.conf.result_backend_max_retries = 0
celery_app.conf.result_backend_transport_options = {
    "socket_connect_timeout": 5,
    "socket_timeout": 5,
    "retry_policy": {"max_retries": 0},
}

# ---------------------------------------------------------------------------
# Task routing — queues and routes derived from shared queue constants
# ---------------------------------------------------------------------------

_all_queue_names: list[str] = list(PRIORITY_QUEUES.values()) + list(
    TRIGGER_TYPE_QUEUES.values()
)

celery_app.conf.update(
    task_queues=[Queue(name) for name in _all_queue_names],
    # ``run_pipeline`` defaults to the normal-priority queue here so background
    # tasks dispatched without an explicit ``queue=`` argument still land on a
    # real queue. API callers (e.g. /tasks/collect) override this per request
    # by passing ``queue=PRIORITY_QUEUES[<priority>]`` to ``send_task`` so
    # high/low traffic is segregated.
    task_routes={
        "run_pipeline": {"queue": PRIORITY_QUEUES["normal"]},
    },
)

# Eagerly import task modules so worker processes (`celery -A
# intellisource.scheduler.celery_app worker`) register handlers at startup —
# without this, the worker boots with [tasks] empty and silently drops every
# message. Late-imported at module end to avoid the circular dependency
# (tasks.py imports celery_app from this module).
from intellisource.scheduler import tasks as _tasks  # noqa: E402, F401
