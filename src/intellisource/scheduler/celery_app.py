"""Module-level Celery application singleton for IntelliSource (T-083 AC-1)."""

from __future__ import annotations

import os

from celery import Celery

# ---------------------------------------------------------------------------
# Broker / backend resolution — reads environment, falls back to memory://
# ---------------------------------------------------------------------------

_CELERY_BROKER_URL: str = (
    os.environ.get("IS_CELERY_BROKER_URL")
    or os.environ.get("IS_REDIS_URL")
    or "memory://"
)

_CELERY_RESULT_BACKEND: str = (
    os.environ.get("IS_CELERY_RESULT_BACKEND")
    or os.environ.get("IS_REDIS_URL")
    or "cache+memory://"
)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

celery_app = Celery(
    "intellisource",
    broker=_CELERY_BROKER_URL,
    backend=_CELERY_RESULT_BACKEND,
)

celery_app.conf.broker_connection_retry_on_startup = False
