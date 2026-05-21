"""Module-level Celery application singleton for IntelliSource (T-083 AC-1)."""

from __future__ import annotations

import os

from celery import Celery


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
