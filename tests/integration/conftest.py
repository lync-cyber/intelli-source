"""Integration test fixtures for T-081.

Provides pg_container (session-scoped pgvector PostgreSQL container),
pg_session (function-scoped SAVEPOINT-isolated AsyncSession), and
pg_truncate (function-scoped teardown TRUNCATE fixture).
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, AsyncIterator

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from intellisource.storage.models import Base

# ---------------------------------------------------------------------------
# Docker availability check — used by pytest_collection_modifyitems to skip
# all pg_* dependent tests when Docker is not running.
# ---------------------------------------------------------------------------


def _docker_is_available() -> bool:
    """Return True if the local Docker daemon is reachable."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


_DOCKER_AVAILABLE: bool | None = None


def _get_docker_available() -> bool:
    global _DOCKER_AVAILABLE
    if _DOCKER_AVAILABLE is None:
        _DOCKER_AVAILABLE = _docker_is_available()
    return _DOCKER_AVAILABLE


# ---------------------------------------------------------------------------
# pytest hook: skip pg_container-dependent tests when Docker is unavailable
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip all tests that depend on pg_container / pg_session / pg_truncate
    when the local Docker daemon is not running."""
    if _get_docker_available():
        return

    skip_marker = pytest.mark.skip(
        reason="Docker daemon not available locally — integration tests skipped; "
        "GREEN verification deferred to CI (ubuntu-latest with built-in Docker)"
    )
    pg_fixtures = {"pg_container", "pg_session", "pg_truncate"}
    for item in items:
        if hasattr(item, "fixturenames"):
            if pg_fixtures.intersection(item.fixturenames):
                item.add_marker(skip_marker)


# ---------------------------------------------------------------------------
# AC-2a: pg_container — session-scoped pgvector container
# ---------------------------------------------------------------------------


def _patch_alembic_for_zhparser(op_module: Any) -> Any:
    """Monkeypatch alembic.op.execute to silently skip zhparser-related DDL."""
    original_execute = op_module.execute

    def _patched_execute(sql: Any, *args: Any, **kwargs: Any) -> Any:
        sql_str = str(sql)
        if "zhparser" in sql_str.lower():
            return None
        return original_execute(sql, *args, **kwargs)

    op_module.execute = _patched_execute
    return original_execute


@pytest.fixture(scope="session")
async def pg_container() -> AsyncIterator[str]:
    """Yield an asyncpg-compatible URL for a pgvector/pgvector:pg16 container.

    Runs alembic upgrade head once per session, with zhparser CREATE EXTENSION
    patched out (not available in the pgvector image). Also creates pg_trgm
    extension required for gin_trgm_ops indexes.
    """
    from testcontainers.postgres import (
        PostgresContainer,  # type: ignore[import-untyped]
    )

    container = PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg")
    container.start()
    original_op_execute = None
    try:
        # Build asyncpg URL
        async_url: str = container.get_connection_url()
        if not async_url.startswith("postgresql+asyncpg://"):
            # Normalize — testcontainers may return postgresql+psycopg2://
            async_url = async_url.replace("postgresql://", "postgresql+asyncpg://")
            async_url = async_url.replace(
                "postgresql+psycopg2://", "postgresql+asyncpg://"
            )

        # Build sync URL for DDL + alembic
        sync_url = async_url.replace("+asyncpg", "")

        # Install required extensions via psycopg (sync) before alembic
        import psycopg  # type: ignore[import-untyped]

        with psycopg.connect(sync_url, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

        # Set DATABASE_URL so alembic env.py can pick it up. alembic runs sync
        # so the URL must drop the asyncpg driver suffix; otherwise env.py
        # overrides the sync URL set on cfg below and SQLAlchemy hits
        # MissingGreenlet while bridging asyncpg through sync engine_from_config.
        os.environ["DATABASE_URL"] = sync_url

        # Patch alembic.op.execute to skip zhparser DDL
        from alembic import op as alembic_op  # type: ignore[import-untyped]

        original_op_execute = _patch_alembic_for_zhparser(alembic_op)

        # Run alembic upgrade head
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic/alembic.ini")
        cfg.set_main_option("sqlalchemy.url", sync_url)
        command.upgrade(cfg, "head")

        yield async_url
    finally:
        # Restore alembic.op.execute if patched
        if original_op_execute is not None:
            try:
                from alembic import op as alembic_op  # type: ignore[import-untyped]

                alembic_op.execute = original_op_execute
            except Exception:
                pass
        container.stop()


# ---------------------------------------------------------------------------
# AC-2b: pg_session — function-scoped SAVEPOINT-isolated AsyncSession
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
async def pg_session(pg_container: str) -> AsyncIterator[AsyncSession]:
    """Yield a SAVEPOINT-isolated AsyncSession backed by the pg_container DB.

    The outer transaction is rolled back after each test, so data does not
    persist between tests.
    """
    engine = create_async_engine(pg_container, echo=False)
    try:
        async with engine.connect() as conn:
            # Begin outer transaction (will be rolled back in finally)
            trans = await conn.begin()
            async with AsyncSession(bind=conn, expire_on_commit=False) as sess:
                # Start the first SAVEPOINT
                await sess.begin_nested()

                @event.listens_for(sess.sync_session, "after_transaction_end")
                def restart_savepoint(session: Any, transaction: Any) -> None:
                    """Restart SAVEPOINT after each flush/commit inside the session."""
                    if transaction.nested and not transaction._parent.nested:
                        session.begin_nested()

                try:
                    yield sess
                finally:
                    await trans.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# AC-2c: pg_truncate — function-scoped teardown TRUNCATE fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
async def pg_truncate(pg_container: str) -> AsyncIterator[None]:
    """Teardown fixture that TRUNCATEs all business tables after each test.

    Yields immediately; the TRUNCATE runs in the teardown phase.
    """
    yield
    engine = create_async_engine(pg_container, echo=False)
    try:
        async with engine.begin() as conn:
            table_names = ", ".join(f'"{t}"' for t in Base.metadata.tables.keys())
            await conn.execute(
                text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
            )
    finally:
        await engine.dispose()
