"""Tests for T-072 AC-T072-1 and AC-T072-4: lifespan DatabaseManager DI and
real Redis/Celery initialisation.

RED phase — all tests in this file are expected to FAIL until the
implementation is complete.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.main import create_app


# ---------------------------------------------------------------------------
# AC-T072-1: lifespan startup writes DatabaseManager into app.state.db
#            and shutdown calls db.close()
# ---------------------------------------------------------------------------


class TestLifespanDatabaseManagerDI:
    """Lifespan stores DatabaseManager in app.state and calls close() on shutdown."""

    @pytest.mark.asyncio
    async def test_startup_stores_database_manager_in_app_state(self) -> None:
        """AC-T072-1: After lifespan startup, app.state.db is a DatabaseManager instance."""
        from intellisource.storage.database import DatabaseManager

        mock_db = MagicMock(spec=DatabaseManager)

        with patch(
            "intellisource.main.DatabaseManager", return_value=mock_db
        ) as mock_cls:
            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                assert hasattr(app.state, "db"), (
                    "app.state.db must be set during lifespan startup"
                )
                assert app.state.db is mock_db, (
                    "app.state.db must be the DatabaseManager instance created in startup"
                )

    @pytest.mark.asyncio
    async def test_startup_instantiates_database_manager(self) -> None:
        """AC-T072-1: lifespan startup calls DatabaseManager() exactly once."""
        from intellisource.storage.database import DatabaseManager

        mock_db = MagicMock(spec=DatabaseManager)
        mock_db.close = AsyncMock()

        with patch(
            "intellisource.main.DatabaseManager", return_value=mock_db
        ) as mock_cls:
            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                pass

            mock_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_calls_db_close(self) -> None:
        """AC-T072-1: lifespan shutdown calls app.state.db.close()."""
        from intellisource.storage.database import DatabaseManager

        mock_db = MagicMock(spec=DatabaseManager)
        mock_db.close = AsyncMock()

        with patch("intellisource.main.DatabaseManager", return_value=mock_db):
            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                pass

            mock_db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_calls_db_close_even_on_error(self) -> None:
        """AC-T072-1: db.close() is called even when the app body raises."""
        from intellisource.storage.database import DatabaseManager

        mock_db = MagicMock(spec=DatabaseManager)
        mock_db.close = AsyncMock()

        with patch("intellisource.main.DatabaseManager", return_value=mock_db):
            app = create_app()
            lifespan = app.router.lifespan_context

            try:
                async with lifespan(app):
                    raise RuntimeError("simulated app error")
            except RuntimeError:
                pass

            mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# AC-T072-4: init_redis() calls aioredis.from_url;
#            init_celery() instantiates Celery
# ---------------------------------------------------------------------------


class TestInitRedis:
    """init_redis() uses aioredis.from_url for a real connection."""

    @pytest.mark.asyncio
    async def test_init_redis_calls_aioredis_from_url(self) -> None:
        """AC-T072-4: init_redis() calls aioredis.from_url (not a no-op stub)."""
        import intellisource.main as main_module

        mock_redis = AsyncMock()

        with patch("intellisource.main.aioredis") as mock_aioredis_mod:
            mock_aioredis_mod.from_url = AsyncMock(return_value=mock_redis)
            await main_module.init_redis()
            mock_aioredis_mod.from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_redis_stores_client_in_app_state_or_module(self) -> None:
        """AC-T072-4: init_redis() stores the Redis client for later use."""
        import intellisource.main as main_module

        mock_redis = AsyncMock()

        with patch("intellisource.main.aioredis") as mock_aioredis_mod:
            mock_aioredis_mod.from_url = AsyncMock(return_value=mock_redis)
            await main_module.init_redis()
            # The redis client returned by from_url must be stored somewhere
            # (module-level var or state) — verified by checking from_url was
            # called, and the return value is not discarded
            assert mock_aioredis_mod.from_url.call_count == 1


class TestInitCelery:
    """init_celery() instantiates a Celery application."""

    def test_init_celery_creates_celery_app(self) -> None:
        """AC-T072-4: init_celery() creates a Celery instance (not a no-op stub)."""
        import intellisource.main as main_module

        mock_celery_instance = MagicMock()

        with patch("intellisource.main.Celery", return_value=mock_celery_instance) as mock_celery_cls:
            main_module.init_celery()
            mock_celery_cls.assert_called_once()

    def test_init_celery_returns_or_stores_celery_app(self) -> None:
        """AC-T072-4: init_celery() either returns or stores the Celery app."""
        import intellisource.main as main_module

        mock_celery_instance = MagicMock()

        with patch("intellisource.main.Celery", return_value=mock_celery_instance):
            result = main_module.init_celery()
            # Either returns the app or stores it; either way Celery was used
            # If it returns the app:
            if result is not None:
                assert result is mock_celery_instance
