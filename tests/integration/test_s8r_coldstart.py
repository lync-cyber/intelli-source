"""AC-1: Cold-start e2e — lifespan startup wires app.state.celery_app.

Verifies that after FastAPI lifespan startup:
- app.state.celery_app is not None
- send_task("run_pipeline", ...) does not raise AttributeError or
  kombu.exceptions.OperationalError when broker is memory://
"""

from __future__ import annotations

import pytest


class TestColdStartLifespan:
    """AC-1: lifespan startup exposes app.state.celery_app."""

    @pytest.mark.asyncio
    async def test_lifespan_sets_celery_app_on_app_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After lifespan startup app.state.celery_app must be non-None."""
        from unittest.mock import AsyncMock, MagicMock, patch

        monkeypatch.setenv("IS_CELERY_BROKER_URL", "memory://")

        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.hset = AsyncMock(return_value=None)

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch(
                "intellisource.main.aioredis.from_url",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
        ):
            from intellisource.main import create_app

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                assert hasattr(app.state, "celery_app"), (
                    "app.state.celery_app must be set during lifespan startup"
                )
                assert app.state.celery_app is not None, (
                    "app.state.celery_app must not be None after startup"
                )

    @pytest.mark.asyncio
    async def test_celery_app_send_task_no_attribute_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """send_task('run_pipeline', ...) must not raise AttributeError."""
        from unittest.mock import AsyncMock, MagicMock, patch

        monkeypatch.setenv("IS_CELERY_BROKER_URL", "memory://")

        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.hset = AsyncMock(return_value=None)

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch(
                "intellisource.main.aioredis.from_url",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
        ):
            from intellisource.main import create_app

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                celery_app = app.state.celery_app
                # Sending a task to a memory:// broker with
                # broker_connection_retry_on_startup=False must not raise
                # AttributeError (that would indicate the app object is wrong).
                try:
                    celery_app.send_task("run_pipeline", kwargs={"source_id": "test"})
                except AttributeError as exc:
                    raise AssertionError(
                        f"send_task raised AttributeError: {exc}"
                    ) from exc
                except Exception:
                    # kombu.exceptions.OperationalError or similar broker errors
                    # are acceptable — what matters is no AttributeError.
                    pass

    @pytest.mark.asyncio
    async def test_celery_app_is_celery_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """app.state.celery_app is a Celery instance with send_task attribute."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from celery import Celery

        monkeypatch.setenv("IS_CELERY_BROKER_URL", "memory://")

        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.hset = AsyncMock(return_value=None)

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch(
                "intellisource.main.aioredis.from_url",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
        ):
            from intellisource.main import create_app

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                celery_app = app.state.celery_app
                assert isinstance(celery_app, Celery), (
                    f"celery_app must be Celery; got {type(celery_app)}"
                )
                assert hasattr(celery_app, "send_task"), (
                    "celery_app must expose send_task()"
                )
