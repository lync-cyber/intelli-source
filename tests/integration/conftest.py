"""Integration test fixtures.

Provides pg_container (session-scoped pgvector PostgreSQL container),
pg_session (function-scoped SAVEPOINT-isolated AsyncSession), and
pg_truncate (function-scoped teardown TRUNCATE fixture).
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from typing import Any, AsyncIterator

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from intellisource.storage.models import Base

_logger = logging.getLogger(__name__)

# Per-fixture teardown deadline. asyncpg engine.dispose() occasionally hangs in
# CI when several function-scoped fixtures (pg_session + pg_truncate) close
# back-to-back; the suite-wide pytest --timeout=300 then escalates a fixture
# stall into a full suite abort. Bound each teardown to 30s and log a warning
# instead — a leaked connection is preferable to losing the rest of the suite.
_TEARDOWN_TIMEOUT_S: float = 30.0

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
    """Deselect pg_container / pg_session / pg_truncate tests when Docker
    is unavailable locally.

    Set ``IS_FORCE_DOCKER_TESTS=1`` (or pass ``--collect-only``) to keep the
    tests in the collection even when Docker is missing — useful for
    inspecting which integration tests would run, and required by CI where
    the Docker daemon is always available so we want a hard failure if the
    detection misfires.
    """
    if _get_docker_available():
        return
    if os.environ.get("IS_FORCE_DOCKER_TESTS") == "1":
        return

    pg_fixtures = {"pg_container", "pg_session", "pg_truncate"}
    deselected: list[pytest.Item] = []
    remaining: list[pytest.Item] = []
    for item in items:
        fixturenames = getattr(item, "fixturenames", ())
        if pg_fixtures.intersection(fixturenames):
            deselected.append(item)
        else:
            remaining.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = remaining


# ---------------------------------------------------------------------------
# AC-2a: pg_container — session-scoped composite pgvector+zhparser container
# ---------------------------------------------------------------------------

_TEST_DB_IMAGE: str = os.environ.get(
    "IS_TEST_DB_IMAGE", "intellisource/db:pg16-pgvector-zhparser"
)


def _docker_image_exists(image: str) -> bool:
    """Return True if *image* is present locally."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _build_test_db_image(image: str) -> None:
    """Build the composite pgvector+zhparser image from docker/db.Dockerfile.

    The integration suite always wants the zhparser-equipped image so the FTS
    SQL paths exercised by storage/vector.py resolve `to_tsvector('zhparser', ...)`
    rather than falling back to the built-in `simple` parser.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    dockerfile = os.path.join(project_root, "docker", "db.Dockerfile")
    if not os.path.exists(dockerfile):
        raise RuntimeError(
            f"docker/db.Dockerfile not found at {dockerfile}; cannot build {image}"
        )
    _logger.info("Building %s from %s (one-off, may take a minute)", image, dockerfile)
    result = subprocess.run(
        ["docker", "build", "-t", image, "-f", dockerfile, project_root],
        capture_output=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker build {image} failed (exit {result.returncode}); "
            f"stderr tail: {result.stderr.decode(errors='replace')[-2000:]}"
        )


@pytest.fixture(scope="session")
async def pg_container() -> AsyncIterator[str]:
    """Yield an asyncpg-compatible URL for the composite pgvector+zhparser container.

    Uses `intellisource/db:pg16-pgvector-zhparser` (override with `IS_TEST_DB_IMAGE`).
    The image is built lazily from docker/db.Dockerfile if it is missing locally,
    so CI and dev machines share the same path without pre-pull rituals. Runs
    `alembic upgrade head` once per session to create the schema, all extensions
    (vector / pg_trgm / zhparser), and the `zhparser` text-search configuration.
    """
    from testcontainers.postgres import PostgresContainer

    if not _docker_image_exists(_TEST_DB_IMAGE):
        _build_test_db_image(_TEST_DB_IMAGE)

    container = PostgresContainer(_TEST_DB_IMAGE, driver="asyncpg")
    container.start()
    try:
        # Build asyncpg URL
        async_url: str = container.get_connection_url()
        if not async_url.startswith("postgresql+asyncpg://"):
            # Normalize — testcontainers may return postgresql+psycopg2://
            async_url = async_url.replace("postgresql://", "postgresql+asyncpg://")
            async_url = async_url.replace(
                "postgresql+psycopg2://", "postgresql+asyncpg://"
            )

        sync_url = async_url.replace("+asyncpg", "+psycopg")

        # Set DATABASE_URL so alembic env.py can pick it up. alembic runs sync
        # so the URL must drop the asyncpg driver suffix; otherwise env.py
        # overrides the sync URL set on cfg below and SQLAlchemy hits
        # MissingGreenlet while bridging asyncpg through sync engine_from_config.
        os.environ["DATABASE_URL"] = sync_url

        # Run alembic upgrade head
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic/alembic.ini")
        cfg.set_main_option("sqlalchemy.url", sync_url)
        command.upgrade(cfg, "head")

        yield async_url
    finally:
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
        try:
            await asyncio.wait_for(engine.dispose(), timeout=_TEARDOWN_TIMEOUT_S)
        except asyncio.TimeoutError:
            _logger.warning(
                "pg_session engine.dispose() exceeded %.1fs; leaked async pool",
                _TEARDOWN_TIMEOUT_S,
            )


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

    async def _truncate() -> None:
        async with engine.begin() as conn:
            table_names = ", ".join(f'"{t}"' for t in Base.metadata.tables.keys())
            await conn.execute(
                text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
            )

    try:
        # wait_for guards against pg_session's outer transaction still holding
        # row locks when fixtures finalize in LIFO order (pg_truncate
        # finalizes before pg_session's outer trans.rollback runs) — TRUNCATE
        # would otherwise block on those locks for the full pytest-session
        # timeout instead of failing fast.
        await asyncio.wait_for(_truncate(), timeout=_TEARDOWN_TIMEOUT_S)
    except asyncio.TimeoutError:
        _logger.warning(
            "pg_truncate TRUNCATE exceeded teardown deadline; skipping cleanup"
        )
    finally:
        try:
            await asyncio.wait_for(engine.dispose(), timeout=_TEARDOWN_TIMEOUT_S)
        except asyncio.TimeoutError:
            _logger.warning(
                "pg_truncate engine.dispose() exceeded %.1fs; leaked async pool",
                _TEARDOWN_TIMEOUT_S,
            )
