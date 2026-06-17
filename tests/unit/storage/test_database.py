"""Tests for Database connection management and ORM base.

Covers:
  AC-T002-1: DatabaseManager connects to a test database via AsyncSession
  AC-T002-2: Connection pool parameters configurable via env var (IS_DATABASE_URL)
  AC-T002-3: Session context manager handles commit/rollback correctly
  AC-T002-4: Connection pool properly released on application shutdown
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from sqlalchemy import Column, Integer, String, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

# ---------------------------------------------------------------------------
# Test-local ORM model for exercising session operations
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _DummyModel(_Base):
    """Throwaway model used only within these tests."""

    __tablename__ = "test_dummy"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


# ===========================================================================
# AC-T002-1: DatabaseManager connects via AsyncSession
# ===========================================================================


class TestDatabaseManagerConnection:
    """AC-T002-1: DatabaseManager through AsyncSession successfully connects
    to a test database."""

    @pytest.mark.asyncio
    async def test_import_database_manager(self) -> None:
        """DatabaseManager class must be importable from the storage module."""
        from intellisource.storage.database import DatabaseManager

        assert isinstance(DatabaseManager, type)

    @pytest.mark.asyncio
    async def test_create_instance_with_url(self) -> None:
        """DatabaseManager can be instantiated with a database URL string."""
        from intellisource.storage.database import DatabaseManager

        manager = DatabaseManager(database_url=SQLITE_TEST_URL)
        assert isinstance(manager, DatabaseManager)

    @pytest.mark.asyncio
    async def test_engine_property_returns_async_engine(self) -> None:
        """DatabaseManager.engine exposes the underlying AsyncEngine."""
        from intellisource.storage.database import DatabaseManager

        manager = DatabaseManager(database_url=SQLITE_TEST_URL)
        engine = manager.engine
        assert engine is not None
        # The engine should be an AsyncEngine from SQLAlchemy
        from sqlalchemy.ext.asyncio import AsyncEngine

        assert isinstance(engine, AsyncEngine)

    @pytest.mark.asyncio
    async def test_get_session_returns_async_session(self) -> None:
        """get_session() must yield an AsyncSession instance."""
        from intellisource.storage.database import DatabaseManager

        manager = DatabaseManager(database_url=SQLITE_TEST_URL)

        # Create tables for the in-memory DB
        async with manager.engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)

        async with manager.get_session() as session:
            assert isinstance(session, AsyncSession)

        await manager.close()

    @pytest.mark.asyncio
    async def test_session_can_execute_query(self) -> None:
        """A session obtained from DatabaseManager can execute a simple query."""
        from intellisource.storage.database import DatabaseManager

        manager = DatabaseManager(database_url=SQLITE_TEST_URL)

        async with manager.engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)

        async with manager.get_session() as session:
            result = await session.execute(text("SELECT 1"))
            row = result.scalar()
            assert row == 1

        await manager.close()


# ===========================================================================
# AC-T002-2: Connection pool configurable via IS_DATABASE_URL env var
# ===========================================================================


class TestDatabaseManagerEnvConfig:
    """AC-T002-2: Connection pool parameters are configurable through the
    IS_DATABASE_URL environment variable."""

    @pytest.mark.asyncio
    async def test_database_manager_reads_env_variable(self) -> None:
        """DatabaseManager (or its config) must honour IS_DATABASE_URL."""
        from intellisource.storage.database import DatabaseManager

        test_url = "sqlite+aiosqlite:///:memory:"
        with patch.dict(os.environ, {"IS_DATABASE_URL": test_url}):
            # When no explicit URL is passed, it should fall back to env var
            manager = DatabaseManager()
            assert str(manager.engine.url) == test_url
            await manager.close()

    @pytest.mark.asyncio
    async def test_explicit_url_overrides_env(self) -> None:
        """An explicitly passed database_url takes precedence over the env var."""
        from intellisource.storage.database import DatabaseManager

        explicit_url = "sqlite+aiosqlite:///:memory:"
        with patch.dict(
            os.environ, {"IS_DATABASE_URL": "sqlite+aiosqlite:///other.db"}
        ):
            manager = DatabaseManager(database_url=explicit_url)
            assert str(manager.engine.url) == explicit_url
            await manager.close()

    @pytest.mark.asyncio
    async def test_missing_url_uses_dev_fallback(self) -> None:
        """No URL env vars and no ENV set results in sqlite dev fallback."""
        from intellisource.storage.database import DatabaseManager

        with patch.dict(os.environ, {}, clear=True):
            manager = DatabaseManager()
            assert (
                str(manager.engine.url) == "sqlite+aiosqlite:///./intellisource_dev.db"
            )
            await manager.close()


# ===========================================================================
# AC-T002-3: Session context manager handles commit/rollback
# ===========================================================================


class TestSessionCommitRollback:
    """AC-T002-3: The session context manager correctly commits on success
    and rolls back on exception."""

    @pytest.mark.asyncio
    async def test_session_commits_on_success(self) -> None:
        """Data persisted inside the context manager is committed."""
        from intellisource.storage.database import DatabaseManager

        manager = DatabaseManager(database_url=SQLITE_TEST_URL)

        async with manager.engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)

        # Insert a row inside a successful session
        async with manager.get_session() as session:
            session.add(_DummyModel(name="committed"))

        # Verify the row was committed by reading it in a new session
        async with manager.get_session() as session:
            result = await session.execute(
                text("SELECT name FROM test_dummy WHERE name = 'committed'")
            )
            row = result.scalar_one_or_none()
            assert row == "committed"

        await manager.close()

    @pytest.mark.asyncio
    async def test_session_rolls_back_on_exception(self) -> None:
        """If an exception occurs inside the session context, changes are
        rolled back and the exception propagates."""
        from intellisource.storage.database import DatabaseManager

        manager = DatabaseManager(database_url=SQLITE_TEST_URL)

        async with manager.engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)

        # Attempt an insert that will be rolled back due to an exception
        with pytest.raises(RuntimeError, match="forced rollback"):
            async with manager.get_session() as session:
                session.add(_DummyModel(name="should_not_persist"))
                raise RuntimeError("forced rollback")

        # Verify the row was NOT committed
        async with manager.get_session() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM test_dummy WHERE name = 'should_not_persist'"
                )
            )
            count = result.scalar()
            assert count == 0

        await manager.close()

    @pytest.mark.asyncio
    async def test_session_usable_after_rollback(self) -> None:
        """After a rollback, subsequent sessions must still work correctly."""
        from intellisource.storage.database import DatabaseManager

        manager = DatabaseManager(database_url=SQLITE_TEST_URL)

        async with manager.engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)

        # Trigger a rollback
        with pytest.raises(RuntimeError):
            async with manager.get_session() as session:
                session.add(_DummyModel(name="will_rollback"))
                raise RuntimeError("boom")

        # Now use a fresh session successfully
        async with manager.get_session() as session:
            session.add(_DummyModel(name="after_rollback"))

        async with manager.get_session() as session:
            result = await session.execute(
                text("SELECT name FROM test_dummy WHERE name = 'after_rollback'")
            )
            row = result.scalar_one_or_none()
            assert row == "after_rollback"

        await manager.close()


# ===========================================================================
# AC-T002-4: Connection pool released on shutdown
# ===========================================================================


class TestConnectionPoolShutdown:
    """AC-T002-4: When the application shuts down, the connection pool is
    properly released via close()."""

    @pytest.mark.asyncio
    async def test_close_disposes_engine(self) -> None:
        """After close(), the engine should be disposed (no active connections)."""
        from intellisource.storage.database import DatabaseManager

        manager = DatabaseManager(database_url=SQLITE_TEST_URL)

        # Ensure engine is created by accessing it
        _ = manager.engine
        await manager.close()

        # After close, the engine's pool should be invalidated.
        # Attempting to connect should raise or the pool should report disposed.
        pool = manager.engine.pool
        assert pool is not None
        # sqlalchemy.pool.AsyncAdaptedQueuePool sets _invalidate_time on dispose
        # We verify that the manager marks itself as closed or the pool is disposed
        # by checking that creating a new connection raises.
        from sqlalchemy.exc import InvalidRequestError

        with pytest.raises((InvalidRequestError, Exception)):
            async with manager.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self) -> None:
        """Calling close() multiple times must not raise."""
        from intellisource.storage.database import DatabaseManager

        manager = DatabaseManager(database_url=SQLITE_TEST_URL)
        await manager.close()
        # Second call should not raise
        await manager.close()

    @pytest.mark.asyncio
    async def test_get_session_after_close_raises(self) -> None:
        """Using get_session() after close() should raise an error."""
        from intellisource.storage.database import DatabaseManager

        manager = DatabaseManager(database_url=SQLITE_TEST_URL)
        await manager.close()

        with pytest.raises(Exception):
            async with manager.get_session() as session:
                await session.execute(text("SELECT 1"))
