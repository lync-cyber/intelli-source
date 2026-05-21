"""Tests for T-083 AC-3 and AC-8: lifespan mounts celery_app on app.state."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.main import create_app

# ---------------------------------------------------------------------------
# AC-3: lifespan startup mounts celery_app into app.state.celery_app;
#        shutdown calls celery_app.close() or equivalent
# ---------------------------------------------------------------------------


class TestLifespanCeleryAppState:
    """AC-3: After lifespan startup, app.state.celery_app is set and non-None."""

    @pytest.mark.asyncio
    async def test_startup_stores_celery_app_in_app_state(self) -> None:
        """AC-3: app.state.celery_app is set during lifespan startup."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_celery = MagicMock()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch("intellisource.main.aioredis") as mock_redis_mod,
            patch("intellisource.main.init_celery", return_value=mock_celery),
        ):
            mock_redis_mod.from_url = AsyncMock(return_value=AsyncMock())
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
    async def test_startup_celery_app_is_the_returned_instance(self) -> None:
        """AC-3: app.state.celery_app is the instance returned by init_celery()."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_celery = MagicMock()
        mock_celery.close = MagicMock()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch("intellisource.main.aioredis") as mock_redis_mod,
            patch("intellisource.main.init_celery", return_value=mock_celery),
        ):
            mock_redis_mod.from_url = AsyncMock(return_value=AsyncMock())
            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                assert app.state.celery_app is mock_celery, (
                    "app.state.celery_app must be the Celery instance "
                    "from init_celery()"
                )

    @pytest.mark.asyncio
    async def test_shutdown_closes_celery_app(self) -> None:
        """AC-3: lifespan shutdown calls celery_app.close() or equivalent."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_celery = MagicMock()
        mock_celery.close = MagicMock()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch("intellisource.main.aioredis") as mock_redis_mod,
            patch("intellisource.main.init_celery", return_value=mock_celery),
        ):
            mock_redis_mod.from_url = AsyncMock(return_value=AsyncMock())
            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                pass

        mock_celery.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_celery_even_on_error(self) -> None:
        """AC-3: celery_app.close() is called even when the app body raises."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_celery = MagicMock()
        mock_celery.close = MagicMock()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch("intellisource.main.aioredis") as mock_redis_mod,
            patch("intellisource.main.init_celery", return_value=mock_celery),
        ):
            mock_redis_mod.from_url = AsyncMock(return_value=AsyncMock())
            app = create_app()
            lifespan = app.router.lifespan_context

            try:
                async with lifespan(app):
                    raise RuntimeError("simulated app error")
            except RuntimeError:
                pass

        mock_celery.close.assert_called_once()


# ---------------------------------------------------------------------------
# AC-8 (unit layer): app.state.celery_app is non-None and send_task accessible
# ---------------------------------------------------------------------------


class TestLifespanCeleryAppSendTask:
    """AC-8 (unit): send_task does not raise AttributeError after lifespan."""

    @pytest.mark.asyncio
    async def test_celery_app_send_task_accessible_after_startup(self) -> None:
        """AC-8: app.state.celery_app.send_task exists without AttributeError."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_celery = MagicMock()
        mock_celery.close = MagicMock()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch("intellisource.main.aioredis") as mock_redis_mod,
            patch("intellisource.main.init_celery", return_value=mock_celery),
        ):
            mock_redis_mod.from_url = AsyncMock(return_value=AsyncMock())
            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                celery_app = app.state.celery_app
                assert celery_app is not None

                try:
                    _ = celery_app.send_task
                except AttributeError as exc:
                    pytest.fail(
                        f"app.state.celery_app.send_task raised AttributeError: {exc}"
                    )

    @pytest.mark.asyncio
    async def test_celery_app_not_none_after_startup(self) -> None:
        """AC-8: app.state.celery_app is not None after lifespan startup."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_celery = MagicMock()
        mock_celery.close = MagicMock()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch("intellisource.main.aioredis") as mock_redis_mod,
            patch("intellisource.main.init_celery", return_value=mock_celery),
        ):
            mock_redis_mod.from_url = AsyncMock(return_value=AsyncMock())
            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                assert app.state.celery_app is not None
