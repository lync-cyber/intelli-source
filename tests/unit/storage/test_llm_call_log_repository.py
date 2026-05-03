"""SQL integration tests for LLMCallLogRepository aggregation logic.

Covers R-003 (test-quality): repository-level SQL verification with real SQLite
in-memory database — no mocking of SQL execution paths.

Scenarios:
  1. Multi-record global aggregation (total_calls / total_tokens / avg_latency_ms)
  2. by_model GROUP BY with mixed success/error rows — error_rate correctness
  3. by_date GROUP BY DATE(created_at) — cross-day grouping
  4. Empty table — AC-T060-6 real path (total_calls=0, by_model=[], by_date=[])
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from intellisource.storage.models import Base, LLMCallLog
from intellisource.storage.repositories.llm_call_log import LLMCallLogRepository

# ---------------------------------------------------------------------------
# Fixtures — replicate project SQLite in-memory pattern from test_repositories.py
# ---------------------------------------------------------------------------

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _remove_pg_only_indexes(base: type) -> None:
    """Remove PostgreSQL-specific indexes unsupported by SQLite."""
    for table in base.metadata.tables.values():
        indexes_to_remove = []
        for idx in table.indexes:
            dialect_options = getattr(idx, "dialect_options", {})
            pg_opts = dialect_options.get("postgresql", {})
            if pg_opts.get("using") or pg_opts.get("ops"):
                indexes_to_remove.append(idx)
        for idx in indexes_to_remove:
            table.indexes.discard(idx)


def _set_sqlite_fk_pragma(dbapi_conn, connection_record) -> None:  # type: ignore[type-arg]
    """Enable foreign key enforcement on SQLite connections."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
async def engine():  # type: ignore[misc]
    """Async SQLite in-memory engine with all tables created."""
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)

    _remove_pg_only_indexes(Base)

    # Replace pgvector Vector columns with Text for SQLite compatibility.
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def session(engine):  # type: ignore[misc]
    """AsyncSession bound to the in-memory test engine."""
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as sess:
        yield sess


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_log(
    *,
    model: str = "gpt-4o-mini",
    status: str = "success",
    input_tokens: int = 100,
    output_tokens: int = 50,
    latency_ms: int = 200,
    created_at: datetime | None = None,
) -> LLMCallLog:
    """Factory for LLMCallLog with sensible defaults."""
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    return LLMCallLog(
        id=uuid.uuid4(),
        model=model,
        provider="openai",
        call_type="summary_generation",
        content_id=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        input_length=len("input"),
        output_length=len("output"),
        status=status,
        error_message=None,
        retry_attempt=None,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# Test 1: Global aggregation over multiple records
# ---------------------------------------------------------------------------


class TestGlobalAggregation:
    """Scenario 1: multiple LLMCallLog rows → correct global totals."""

    async def test_global_totals_with_multiple_records(
        self, session: AsyncSession
    ) -> None:
        """get_stats() returns correct total_calls / total_tokens / avg_latency_ms."""
        now = datetime.now(timezone.utc)
        logs = [
            _make_log(
                input_tokens=100, output_tokens=50, latency_ms=200, created_at=now
            ),
            _make_log(
                input_tokens=200, output_tokens=100, latency_ms=400, created_at=now
            ),
            _make_log(
                input_tokens=300, output_tokens=150, latency_ms=600, created_at=now
            ),
        ]
        session.add_all(logs)
        await session.flush()

        repo = LLMCallLogRepository(session)
        stats = await repo.get_stats(period="day")

        assert stats["total_calls"] == 3
        assert stats["total_input_tokens"] == 600
        assert stats["total_output_tokens"] == 300
        assert stats["total_tokens"] == 900
        # AVG(200, 400, 600) = 400.0
        assert abs(stats["avg_latency_ms"] - 400.0) < 0.01


# ---------------------------------------------------------------------------
# Test 2: by_model GROUP BY with mixed success/error rows
# ---------------------------------------------------------------------------


class TestByModelGroupBy:
    """Scenario 2: mixed success/error rows → correct by_model error_rate."""

    async def test_by_model_grouping_and_error_rate(
        self, session: AsyncSession
    ) -> None:
        """by_model[] correctly groups by model and computes error_rate as float."""
        now = datetime.now(timezone.utc)
        # model-a: 3 calls, 1 error → error_rate = 1/3 ≈ 0.333
        session.add_all(
            [
                _make_log(
                    model="model-a",
                    status="success",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=100,
                    created_at=now,
                ),
                _make_log(
                    model="model-a",
                    status="success",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=100,
                    created_at=now,
                ),
                _make_log(
                    model="model-a",
                    status="error",
                    input_tokens=10,
                    output_tokens=0,
                    latency_ms=50,
                    created_at=now,
                ),
            ]
        )
        # model-b: 2 calls, 0 errors → error_rate = 0.0
        session.add_all(
            [
                _make_log(
                    model="model-b",
                    status="success",
                    input_tokens=20,
                    output_tokens=10,
                    latency_ms=200,
                    created_at=now,
                ),
                _make_log(
                    model="model-b",
                    status="success",
                    input_tokens=20,
                    output_tokens=10,
                    latency_ms=200,
                    created_at=now,
                ),
            ]
        )
        await session.flush()

        repo = LLMCallLogRepository(session)
        stats = await repo.get_stats(period="day")

        by_model = {item["model"]: item for item in stats["by_model"]}
        assert "model-a" in by_model
        assert "model-b" in by_model

        ma = by_model["model-a"]
        assert ma["call_count"] == 3
        assert ma["input_tokens"] == 30
        assert ma["output_tokens"] == 10
        # error_rate must be float in [0.0, 1.0]
        assert isinstance(ma["error_rate"], float)
        assert abs(ma["error_rate"] - (1.0 / 3.0)) < 0.001

        mb = by_model["model-b"]
        assert mb["call_count"] == 2
        assert isinstance(mb["error_rate"], float)
        assert mb["error_rate"] == 0.0


# ---------------------------------------------------------------------------
# Test 3: by_date GROUP BY DATE — cross-day data
# ---------------------------------------------------------------------------


class TestByDateGroupBy:
    """Scenario 3: logs on different dates → by_date[] groups correctly."""

    async def test_by_date_groups_across_days(self, session: AsyncSession) -> None:
        """by_date[] returns one entry per calendar day, ordered ascending."""
        now = datetime.now(timezone.utc).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        d1 = now - timedelta(days=2)
        d2 = now - timedelta(days=1)

        session.add_all(
            [
                _make_log(
                    input_tokens=100, output_tokens=50, latency_ms=100, created_at=d1
                ),
                _make_log(
                    input_tokens=200, output_tokens=100, latency_ms=200, created_at=d1
                ),
                _make_log(
                    input_tokens=300, output_tokens=150, latency_ms=300, created_at=d2
                ),
            ]
        )
        await session.flush()

        repo = LLMCallLogRepository(session)
        stats = await repo.get_stats(period="month")

        by_date = stats["by_date"]
        assert len(by_date) >= 2

        dates = [item["date"] for item in by_date]
        # Dates must be ordered ascending
        assert dates == sorted(dates)

        # Find the two test dates
        d1_str = d1.strftime("%Y-%m-%d")
        d2_str = d2.strftime("%Y-%m-%d")
        date_map = {item["date"]: item for item in by_date}

        assert d1_str in date_map
        assert date_map[d1_str]["call_count"] == 2
        assert date_map[d1_str]["total_tokens"] == 450  # (100+50)+(200+100)

        assert d2_str in date_map
        assert date_map[d2_str]["call_count"] == 1
        assert date_map[d2_str]["total_tokens"] == 450  # 300+150


# ---------------------------------------------------------------------------
# Test 4: Empty table — AC-T060-6 real SQL path
# ---------------------------------------------------------------------------


class TestEmptyTable:
    """Scenario 4: empty llm_call_logs table → safe zero aggregates."""

    async def test_empty_table_returns_zero_aggregates(
        self, session: AsyncSession
    ) -> None:
        """get_stats() on an empty table returns zeros without error."""
        repo = LLMCallLogRepository(session)
        stats = await repo.get_stats(period="day")

        assert stats["total_calls"] == 0
        assert stats["total_tokens"] == 0
        assert stats["total_input_tokens"] == 0
        assert stats["total_output_tokens"] == 0
        assert stats["avg_latency_ms"] == 0.0
        assert stats["by_model"] == []
        assert stats["by_date"] == []
