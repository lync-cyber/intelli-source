"""RED-phase tests for ContentRepository.list_missing_embeddings (T-BF-1 AC-1/AC-2).

AC-1: list_missing_embeddings(batch_size=2, offset=0) returns 2 NULL-embedding rows;
      all returned records have embedding == None; result is a list[ProcessedContent].
AC-2: list_missing_embeddings(batch_size=10, offset=2) returns 1 remaining NULL row;
      offset past the end returns [].

Design: all tests use AsyncMock session — no real DB, no engine, no SQLite/pgvector
incompatibility. The session mock simulates the SQLAlchemy execute -> scalars -> all
chain that list_missing_embeddings will use internally. SQL statement semantics
(IS NULL, LIMIT, OFFSET) are verified by inspecting the compiled statement passed
to session.execute.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.storage.models import ProcessedContent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_null_row(body_text: str = "body") -> MagicMock:
    """Return a MagicMock with spec=ProcessedContent and embedding=None."""
    row = MagicMock(spec=ProcessedContent)
    row.id = uuid.uuid4()
    row.embedding = None
    row.body_text = body_text
    row.title = "Title"
    return row


def _make_mock_session(rows: list) -> AsyncMock:
    """Return an AsyncMock session whose execute returns rows via scalars().all()."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = rows

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


def _extract_stmt(mock_session: AsyncMock):
    """Return the SQLAlchemy statement passed to session.execute."""
    return mock_session.execute.call_args[0][0]


def _compile_stmt(stmt) -> str:
    """Compile the SQLAlchemy statement to a string for semantic assertions."""
    from sqlalchemy.dialects import postgresql  # noqa: PLC0415

    try:
        return str(
            stmt.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
    except Exception:
        # Fallback: use default compile without literal binds
        return str(stmt.compile(compile_kwargs={"literal_binds": True}))


# ---------------------------------------------------------------------------
# AC-1: batch_size=2, offset=0 — returns 2 NULL rows, correct SQL semantics
# ---------------------------------------------------------------------------


class TestListMissingEmbeddingsAC1:
    """AC-1: list_missing_embeddings(batch_size=2, offset=0) returns 2 NULL rows."""

    @pytest.mark.asyncio
    async def test_returns_list_of_length_batch_size(self) -> None:
        """Result must be a list of exactly batch_size items when NULL rows exist."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        null_rows = [_make_null_row(f"body {i}") for i in range(2)]
        mock_session = _make_mock_session(null_rows)

        repo = ContentRepository(mock_session)
        result = await repo.list_missing_embeddings(batch_size=2, offset=0)

        assert isinstance(result, list), "list_missing_embeddings must return a list"
        assert len(result) == 2, (
            f"batch_size=2 with 2 NULL rows must return exactly 2, got {len(result)}"
        )

    @pytest.mark.asyncio
    async def test_returned_rows_have_null_embedding(self) -> None:
        """Every returned row must have embedding == None."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        null_rows = [_make_null_row() for _ in range(2)]
        mock_session = _make_mock_session(null_rows)

        repo = ContentRepository(mock_session)
        result = await repo.list_missing_embeddings(batch_size=2, offset=0)

        assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
        for row in result:
            assert row.embedding is None, (
                f"Returned row must have embedding=None, got {row.embedding!r}"
            )

    @pytest.mark.asyncio
    async def test_sql_contains_is_null_filter(self) -> None:
        """The statement passed to execute must have an IS NULL filter on embedding."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        mock_session = _make_mock_session([])

        repo = ContentRepository(mock_session)
        await repo.list_missing_embeddings(batch_size=2, offset=0)

        assert mock_session.execute.called, "session.execute must be called"
        stmt = _extract_stmt(mock_session)
        sql = _compile_stmt(stmt).upper()
        assert "IS NULL" in sql, (
            f"SQL must contain IS NULL to filter NULL embeddings. Got:\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_sql_contains_limit(self) -> None:
        """The statement must encode LIMIT = batch_size."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        mock_session = _make_mock_session([])

        repo = ContentRepository(mock_session)
        await repo.list_missing_embeddings(batch_size=2, offset=0)

        stmt = _extract_stmt(mock_session)
        sql = _compile_stmt(stmt).upper()
        assert "LIMIT" in sql, (
            f"SQL must contain LIMIT clause for pagination. Got:\n{sql}"
        )
        # LIMIT value must be 2 (batch_size)
        assert "2" in sql, f"SQL must contain LIMIT 2. Got:\n{sql}"

    @pytest.mark.asyncio
    async def test_sql_contains_offset_zero(self) -> None:
        """The statement must encode OFFSET = 0 when offset=0 is passed."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        mock_session = _make_mock_session([])

        repo = ContentRepository(mock_session)
        await repo.list_missing_embeddings(batch_size=2, offset=0)

        stmt = _extract_stmt(mock_session)
        sql = _compile_stmt(stmt).upper()
        assert "OFFSET" in sql, f"SQL must contain OFFSET clause. Got:\n{sql}"

    @pytest.mark.asyncio
    async def test_result_elements_match_mock_rows(self) -> None:
        """Returned list must contain exactly the rows the mock session returned."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        null_rows = [_make_null_row(f"article {i}") for i in range(2)]
        mock_session = _make_mock_session(null_rows)

        repo = ContentRepository(mock_session)
        result = await repo.list_missing_embeddings(batch_size=2, offset=0)

        assert result == null_rows, (
            f"Returned rows must equal the mock rows. "
            f"Expected {null_rows}, got {result}"
        )


# ---------------------------------------------------------------------------
# AC-2: offset semantics — offset=2 returns 1 row; overflow returns []
# ---------------------------------------------------------------------------


class TestListMissingEmbeddingsAC2:
    """AC-2: offset=2 returns the 1 remaining NULL row; offset past end returns []."""

    @pytest.mark.asyncio
    async def test_offset_2_returns_one_row(self) -> None:
        """When mock returns 1 row at offset=2, result list length must be 1."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        remaining_row = _make_null_row("third body")
        mock_session = _make_mock_session([remaining_row])

        repo = ContentRepository(mock_session)
        result = await repo.list_missing_embeddings(batch_size=10, offset=2)

        assert len(result) == 1, (
            f"offset=2 with 1 remaining NULL row must return exactly 1, "
            f"got {len(result)}"
        )
        assert result[0].embedding is None, (
            "The single remaining row must have embedding=None"
        )

    @pytest.mark.asyncio
    async def test_sql_encodes_offset_value(self) -> None:
        """The compiled statement must contain the OFFSET value passed to the method."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        mock_session = _make_mock_session([])

        repo = ContentRepository(mock_session)
        await repo.list_missing_embeddings(batch_size=10, offset=2)

        stmt = _extract_stmt(mock_session)
        sql = _compile_stmt(stmt).upper()
        assert "OFFSET" in sql, f"SQL must contain OFFSET clause. Got:\n{sql}"
        assert "2" in sql, f"SQL OFFSET must encode value 2. Got:\n{sql}"

    @pytest.mark.asyncio
    async def test_offset_past_end_returns_empty_list(self) -> None:
        """When mock returns no rows (offset past end), method must return []."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        mock_session = _make_mock_session([])

        repo = ContentRepository(mock_session)
        result = await repo.list_missing_embeddings(batch_size=10, offset=100)

        assert result == [], (
            f"offset past the last NULL row must return [], got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_offset_past_end_does_not_raise(self) -> None:
        """list_missing_embeddings with overflow offset must not raise."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        mock_session = _make_mock_session([])

        repo = ContentRepository(mock_session)
        # Must not raise — just returns an empty list
        result = await repo.list_missing_embeddings(batch_size=10, offset=999)
        assert isinstance(result, list), "Must return a list even when offset overflows"

    @pytest.mark.asyncio
    async def test_offset_changes_the_offset_in_sql(self) -> None:
        """Two calls with different offsets must pass different OFFSET values."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        mock_session = _make_mock_session([])

        repo = ContentRepository(mock_session)

        await repo.list_missing_embeddings(batch_size=2, offset=0)
        call_1_stmt = mock_session.execute.call_args_list[0][0][0]

        await repo.list_missing_embeddings(batch_size=2, offset=2)
        call_2_stmt = mock_session.execute.call_args_list[1][0][0]

        sql_0 = _compile_stmt(call_1_stmt).upper()
        sql_2 = _compile_stmt(call_2_stmt).upper()

        assert "OFFSET" in sql_0, "First call SQL must have OFFSET"
        assert "OFFSET" in sql_2, "Second call SQL must have OFFSET"
        # The two compiled statements must differ (different OFFSET values)
        assert sql_0 != sql_2, "SQL with offset=0 must differ from SQL with offset=2"
