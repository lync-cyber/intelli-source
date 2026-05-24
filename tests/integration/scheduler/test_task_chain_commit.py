"""Verify that _chain_repo_session() commits on success and rolls back on error.

Uses aiosqlite + SQLAlchemy create_all so no Docker/PostgreSQL is required.
TaskChain uses PostgreSQL-specific column types; this module re-declares a
minimal SQLite-compatible mirror table (task_chains_test) to exercise the
session.begin() commit path without depending on pg_container.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import Integer, String
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import VARCHAR

# ---------------------------------------------------------------------------
# Minimal SQLite-compatible ORM model (mirrors TaskChain without PG types)
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TaskChainSQLite(_TestBase):
    """SQLite-compatible shadow of TaskChain for commit-path testing."""

    __tablename__ = "task_chains_test"

    id: Mapped[str] = mapped_column(VARCHAR(36), primary_key=True)
    pipeline_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# Fixture: in-memory aiosqlite engine + session factory
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def sqlite_session_factory():
    """Yield a session factory backed by an in-memory aiosqlite database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    async def _factory() -> AsyncSession:
        return AsyncSession(engine, expire_on_commit=False)

    yield _factory
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helper: minimal CeleryTasks-like context manager for isolation
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _chain_repo_session_under_test(
    session_factory,
) -> AsyncIterator[AsyncSession]:
    """Reproduce the fixed _chain_repo_session logic for direct testing."""
    session = await session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Test 1: successful write is committed and visible in a fresh session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_on_success(sqlite_session_factory):
    """Data written inside _chain_repo_session is committed to the DB."""
    chain_id = str(uuid.uuid4())

    async with _chain_repo_session_under_test(sqlite_session_factory) as sess:
        obj = _TaskChainSQLite(
            id=chain_id,
            pipeline_name="test_pipe",
            status="pending",
            trigger_type="manual",
            execution_mode="strict",
            total_steps=1,
            completed_steps=0,
        )
        sess.add(obj)
        # flush is safe inside begin(); commit happens on __aexit__

    # Verify with a completely independent session (no shared state)
    verify_session = await sqlite_session_factory()
    try:
        async with verify_session.begin():
            result = await verify_session.get(_TaskChainSQLite, chain_id)
        assert result is not None, "Row must be committed and visible to a new session"
        assert result.pipeline_name == "test_pipe"
        assert result.status == "pending"
    finally:
        await verify_session.close()


# ---------------------------------------------------------------------------
# Test 2: exception inside the context causes rollback — no row persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_on_exception(sqlite_session_factory):
    """An exception inside _chain_repo_session triggers automatic rollback."""
    chain_id = str(uuid.uuid4())

    with pytest.raises(RuntimeError, match="simulated failure"):
        async with _chain_repo_session_under_test(sqlite_session_factory) as sess:
            obj = _TaskChainSQLite(
                id=chain_id,
                pipeline_name="rollback_pipe",
                status="pending",
                trigger_type="scheduled",
                execution_mode="strict",
                total_steps=2,
                completed_steps=0,
            )
            sess.add(obj)
            raise RuntimeError("simulated failure")

    # Verify row was NOT committed
    verify_session = await sqlite_session_factory()
    try:
        async with verify_session.begin():
            result = await verify_session.get(_TaskChainSQLite, chain_id)
        assert result is None, "Row must NOT be present after a rolled-back transaction"
    finally:
        await verify_session.close()


# ---------------------------------------------------------------------------
# Test 3: commit/rollback contract on _chain_repo_session (mock-level guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_called_on_success_and_rollback_on_failure():
    """_chain_repo_session() calls commit on success and rollback on exception."""
    from intellisource.scheduler.tasks import CeleryTasks
    from intellisource.storage.repositories.task_chain import TaskChainRepository

    # --- success path ---
    mock_session_ok = AsyncMock(spec=AsyncSession)

    async def _factory_ok() -> AsyncSession:
        return mock_session_ok

    ct = CeleryTasks(
        agent_runner=MagicMock(),
        pipeline_config=None,
        session_factory=_factory_ok,
    )

    yielded: list[TaskChainRepository] = []
    async with ct._chain_repo_session() as repo:
        yielded.append(repo)

    mock_session_ok.commit.assert_called_once()
    mock_session_ok.rollback.assert_not_called()
    mock_session_ok.close.assert_called_once()
    assert isinstance(yielded[0], TaskChainRepository)

    # --- failure path ---
    mock_session_err = AsyncMock(spec=AsyncSession)

    async def _factory_err() -> AsyncSession:
        return mock_session_err

    ct_err = CeleryTasks(
        agent_runner=MagicMock(),
        pipeline_config=None,
        session_factory=_factory_err,
    )

    with pytest.raises(ValueError, match="boom"):
        async with ct_err._chain_repo_session():
            raise ValueError("boom")

    mock_session_err.rollback.assert_called_once()
    mock_session_err.commit.assert_not_called()
    mock_session_err.close.assert_called_once()
