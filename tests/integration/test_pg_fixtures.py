"""RED-phase tests for T-081: pg_container / pg_session / pg_truncate fixtures.

Validates the fixture contract defined in §interface_contract.  All tests in
this file intentionally FAIL at the RED phase because the fixtures are not yet
defined in tests/integration/conftest.py (GREEN phase responsibility).

Expected failure mode: pytest ERROR — "fixture 'pg_container' not found" or
"fixture 'pg_session' not found" (not SyntaxError or logic bug).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from intellisource.storage.models import ContentCluster

# ---------------------------------------------------------------------------
# AC-2a: pg_container fixture — session-scoped, yields valid asyncpg URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pg_container_yields_valid_url(pg_container: str) -> None:
    """pg_container yields an asyncpg-compatible connection URL."""
    assert pg_container.startswith("postgresql+asyncpg://"), (
        "pg_container URL must start with 'postgresql+asyncpg://', "
        f"got: {pg_container!r}"
    )


@pytest.mark.asyncio
async def test_pg_container_has_pgvector_extension(pg_container: str) -> None:
    """Container DB has the vector extension installed (pgvector:pg16 image)."""
    engine = create_async_engine(pg_container, echo=False)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            rows = result.fetchall()
    finally:
        await engine.dispose()

    assert len(rows) == 1, (
        "Expected exactly 1 row for 'vector' extension in pg_extension, "
        f"got {len(rows)} rows — ensure the pgvector/pgvector:pg16 image is used"
    )
    assert rows[0][0] == "vector", f"Expected extname='vector', got {rows[0][0]!r}"


@pytest.mark.asyncio
async def test_pg_container_runs_alembic_once(pg_container: str) -> None:
    """The fixture runs 'alembic upgrade head' exactly once per session.

    Verifies that the core business tables created by the migration exist.
    """
    expected_tables = {"processed_contents", "content_clusters", "sources"}
    engine = create_async_engine(pg_container, echo=False)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            existing = {row[0] for row in result.fetchall()}
    finally:
        await engine.dispose()

    missing = expected_tables - existing
    assert not missing, (
        f"Alembic upgrade head did not create expected tables: {missing!r}. "
        f"Tables found: {sorted(existing)}"
    )


# ---------------------------------------------------------------------------
# AC-2b: pg_session fixture — function-scoped, yields AsyncSession
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pg_session_yields_async_session(pg_session: AsyncSession) -> None:
    """pg_session fixture yields a live sqlalchemy AsyncSession instance."""
    assert isinstance(pg_session, AsyncSession), (
        f"Expected AsyncSession, got {type(pg_session).__name__!r}"
    )


@pytest.mark.asyncio
async def test_pg_session_can_execute_simple_query(pg_session: AsyncSession) -> None:
    """The AsyncSession from pg_session can execute a trivial SQL query."""
    result = await pg_session.execute(text("SELECT 1 AS val"))
    row = result.fetchone()
    assert row is not None, "Expected a row from 'SELECT 1', got None"
    assert row[0] == 1, f"Expected row[0] == 1, got {row[0]!r}"


# ---------------------------------------------------------------------------
# AC-2b: SAVEPOINT isolation — data from test N must not be visible in test N+1
#
# The two tests below are intentionally sequential and depend on order to prove
# isolation.  They share a module-level counter so the second test can assert
# it runs after the first.
# ---------------------------------------------------------------------------

_isolation_counter: list[str] = []  # accumulated across test collection order


@pytest.mark.asyncio
async def test_pg_session_savepoint_isolation_first_test_inserts(
    pg_session: AsyncSession,
) -> None:
    """First isolation test: insert a ContentCluster row; commit inside the savepoint.

    Savepoint rollback isolates this insert from subsequent tests.

    The savepoint must be rolled back by the fixture before the next test runs,
    so the next test should see an empty content_clusters table.
    """
    cluster = ContentCluster(
        id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
        topic="isolation-sentinel",
        tags=["isolation-test"],
        content_count=0,
        status="active",
    )
    pg_session.add(cluster)
    await pg_session.flush()

    # Verify the row is visible within this transaction.
    result = await pg_session.execute(
        text("SELECT topic FROM content_clusters WHERE topic = 'isolation-sentinel'")
    )
    rows = result.fetchall()
    assert len(rows) == 1, (
        "Expected to find the inserted row within the same savepoint, "
        f"got {len(rows)} rows"
    )
    _isolation_counter.append("first_test_ran")


@pytest.mark.asyncio
async def test_pg_session_savepoint_isolation_second_test_sees_empty(
    pg_session: AsyncSession,
) -> None:
    """Second isolation test: the row inserted by the prior test must NOT be visible.

    This confirms the fixture rolled back the savepoint between tests.
    """
    # Confirm ordering: this test is always collected after the first.
    assert "first_test_ran" in _isolation_counter, (
        "Ordering invariant broken — first isolation test did not run before this one"
    )

    result = await pg_session.execute(
        text("SELECT topic FROM content_clusters WHERE topic = 'isolation-sentinel'")
    )
    rows = result.fetchall()
    assert len(rows) == 0, (
        "SAVEPOINT isolation failed: the row inserted by the previous test is still "
        f"visible ({len(rows)} rows found). The fixture must ROLLBACK TO SAVEPOINT "
        "between tests."
    )


# ---------------------------------------------------------------------------
# AC-2c: pg_truncate fixture — TRUNCATE business tables + RESTART IDENTITY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pg_truncate_clears_business_tables_after_test(
    pg_session: AsyncSession,
    pg_truncate: Any,
) -> None:
    """pg_truncate fixture empties business tables so the next test sees a clean state.

    Inserts one ContentCluster row.  The pg_truncate fixture teardown (after
    yield) must TRUNCATE the table.  This test validates the insert side of the
    cycle; the 'see empty' assertion is covered by
    test_pg_truncate_next_test_sees_empty_table below.
    """
    cluster = ContentCluster(
        id=uuid.uuid4(),
        topic="truncate-test-sentinel",
        tags=["truncate"],
        content_count=0,
        status="active",
    )
    pg_session.add(cluster)
    await pg_session.flush()

    result = await pg_session.execute(
        text(
            "SELECT COUNT(*) FROM content_clusters "
            "WHERE topic = 'truncate-test-sentinel'"
        )
    )
    count = result.scalar()
    assert count == 1, (
        "Expected 1 row after insert, "
        f"got {count!r} — prerequisite for truncate teardown test"
    )


@pytest.mark.asyncio
async def test_pg_truncate_next_test_sees_empty_table(
    pg_session: AsyncSession,
    pg_truncate: Any,
) -> None:
    """After pg_truncate teardown, content_clusters must be empty."""
    result = await pg_session.execute(text("SELECT COUNT(*) FROM content_clusters"))
    count = result.scalar()
    assert count == 0, (
        "pg_truncate fixture did not clear content_clusters between tests: "
        f"found {count} row(s)"
    )
