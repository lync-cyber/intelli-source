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

# ---------------------------------------------------------------------------
# Task routing — queues and routes derived from shared queue constants
# ---------------------------------------------------------------------------

_all_queue_names: list[str] = list(PRIORITY_QUEUES.values()) + list(
    TRIGGER_TYPE_QUEUES.values()
)

celery_app.conf.update(
    task_queues=[Queue(name) for name in _all_queue_names],
    task_routes={
        "run_pipeline": {"queue": PRIORITY_QUEUES["normal"]},
    },
)
