"""Tests for lifespan-managed app.state.celery_app.

Covers AC-3/AC-8. With the unified Celery singleton, lifespan binds
`app.state.celery_app` to the module-level
`intellisource.scheduler.celery_app.celery_app` and does not call `.close()`
on shutdown (the singleton is owned by the worker process; the API process
is a consumer).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.main import create_app


class TestLifespanCeleryAppState:
    """After lifespan startup, app.state.celery_app is the module singleton."""

    @pytest.mark.asyncio
    async def test_startup_stores_celery_app_in_app_state(self) -> None:
        """app.state.celery_app is set during lifespan startup."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch("intellisource.main.aioredis") as mock_redis_mod,
        ):
            mock_redis_mod.from_url = AsyncMock(return_value=AsyncMock())
            from intellisource.scheduler.celery_app import (
                celery_app as module_celery_app,
            )

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                assert hasattr(app.state, "celery_app")
                assert app.state.celery_app is module_celery_app

    @pytest.mark.asyncio
    async def test_startup_celery_app_is_module_singleton(self) -> None:
        """app.state.celery_app IS the module-level singleton."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch("intellisource.main.aioredis") as mock_redis_mod,
        ):
            mock_redis_mod.from_url = AsyncMock(return_value=AsyncMock())
            from intellisource.scheduler.celery_app import (
                celery_app as module_celery_app,
            )

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                assert app.state.celery_app is module_celery_app


class TestLifespanCeleryAppSendTask:
    """send_task does not raise AttributeError after lifespan."""

    @pytest.mark.asyncio
    async def test_celery_app_send_task_accessible_after_startup(self) -> None:
        """app.state.celery_app.send_task exists without AttributeError."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch("intellisource.main.aioredis") as mock_redis_mod,
        ):
            mock_redis_mod.from_url = AsyncMock(return_value=AsyncMock())
            from intellisource.scheduler.celery_app import (
                celery_app as module_celery_app,
            )

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                celery_app = app.state.celery_app
                assert celery_app is module_celery_app
                try:
                    _ = celery_app.send_task
                except AttributeError as exc:
                    pytest.fail(
                        f"app.state.celery_app.send_task raised AttributeError: {exc}"
                    )

    @pytest.mark.asyncio
    async def test_celery_app_not_none_after_startup(self) -> None:
        """app.state.celery_app is not None after lifespan startup."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch("intellisource.main.aioredis") as mock_redis_mod,
        ):
            mock_redis_mod.from_url = AsyncMock(return_value=AsyncMock())
            from intellisource.scheduler.celery_app import (
                celery_app as module_celery_app,
            )

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                assert app.state.celery_app is module_celery_app
