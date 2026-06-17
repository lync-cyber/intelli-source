"""beat_init signal handler — guards beat process bootstraps schedule from DB.

Production failure:

    beat process runs ``celery -A intellisource.scheduler.celery_app beat`` →
    celery_app.conf.beat_schedule is empty at import time → beat idles
    indefinitely with zero periodic tasks even though Source rows have
    schedule_interval populated.

    Root cause: ``_bootstrap_beat_schedule`` is only invoked from
    ``worker_process_init`` signal, which beat process never fires.

Fix:

1. ``scheduler.boot.beat_init_handler`` is connected to the celery
   ``beat_init`` signal at module import time, with an idempotency guard
   matching the worker_process_init connection pattern.
2. ``docker/docker-compose.yml`` beat service uses
   ``-A intellisource.scheduler.boot`` (not ``.celery_app``) so the signal
   handlers get registered when beat imports the app module.
3. When beat boots, the handler initializes a session_factory and calls
   ``_bootstrap_beat_schedule`` to project Source rows onto
   ``celery_app.conf.beat_schedule``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestBeatInitSignalConnection:
    """beat_init signal must be connected at module import time."""

    def test_beat_init_signal_has_handler(self) -> None:
        from celery.signals import beat_init

        from intellisource.scheduler import (
            boot,  # noqa: F401 — trigger module-level connect
        )

        assert getattr(beat_init, "_intellisource_connected", False) is True

    def test_idempotent_connect_guard_prevents_double_register(self) -> None:
        from celery.signals import beat_init

        from intellisource.scheduler import boot  # noqa: F401

        before_len = len(beat_init.receivers)
        # Re-execute the connect block as if the module were imported twice.
        # The `_intellisource_connected` sentinel must short-circuit.
        if not getattr(beat_init, "_intellisource_connected", False):
            beat_init.connect(boot.beat_init_handler)
            beat_init._intellisource_connected = True
        after_len = len(beat_init.receivers)
        assert after_len == before_len


class TestBeatInitHandler:
    """beat_init_handler bootstraps the schedule from DB."""

    def test_handler_calls_bootstrap_with_session_factory(self) -> None:
        from intellisource.scheduler import boot

        sentinel_factory = MagicMock(name="session_factory")
        with (
            patch.object(
                boot, "init_worker_session_factory", return_value=sentinel_factory
            ) as mock_init_factory,
            patch.object(boot, "_bootstrap_beat_schedule") as mock_bootstrap,
        ):
            boot.beat_init_handler()

        mock_init_factory.assert_called_once_with()
        mock_bootstrap.assert_called_once_with(sentinel_factory)

    def test_handler_ignores_extra_kwargs(self) -> None:
        """Celery passes sender + arbitrary kwargs; handler must accept them."""
        from intellisource.scheduler import boot

        with (
            patch.object(boot, "init_worker_session_factory", return_value=MagicMock()),
            patch.object(boot, "_bootstrap_beat_schedule"),
        ):
            boot.beat_init_handler(sender=MagicMock(), extra="ignored")

    def test_handler_propagates_bootstrap_errors(self) -> None:
        """DB connection failures during bootstrap surface, not silently swallow."""
        from intellisource.scheduler import boot

        with (
            patch.object(boot, "init_worker_session_factory", return_value=MagicMock()),
            patch.object(
                boot, "_bootstrap_beat_schedule", side_effect=RuntimeError("db down")
            ),
        ):
            with pytest.raises(RuntimeError, match="db down"):
                boot.beat_init_handler()
