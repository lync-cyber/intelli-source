"""Unit regression test for T-096 R-001:

`_RawContentResultRepo.create` must call `session.commit()` after updating
the RawContent row, otherwise the status/processed_at writes are rolled
back when the AsyncSession context exits (default autocommit=False).

This unit-level test uses MagicMock sessions so it runs without Docker —
the existing integration test
(tests/integration/test_raw_content_persist_on_pipeline_done.py) covers the
end-to-end DB persistence in CI.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.scheduler.boot import _RawContentResultRepo


def _make_session_factory(row: Any = None) -> tuple[Any, AsyncMock]:
    """Return (session_factory, session_mock) recording commit calls."""
    session_mock = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=row)
    session_mock.execute = AsyncMock(return_value=execute_result)
    session_mock.commit = AsyncMock()
    session_mock.flush = AsyncMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session_mock)
    cm.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=cm)
    return session_factory, session_mock


@pytest.mark.asyncio
async def test_create_calls_session_commit_when_row_found() -> None:
    """Regression: AC-6 persistence requires session.commit() (not just flush)."""
    row = MagicMock()
    row.status = "pending"
    row.processed_at = None
    session_factory, session_mock = _make_session_factory(row=row)
    repo = _RawContentResultRepo(session_factory=session_factory)

    result = await repo.create({"content_id": str(uuid.uuid4()), "tool": "process"})

    assert session_mock.commit.await_count == 1, (
        "R-001 regression: _RawContentResultRepo.create must call session.commit() "
        f"after updating RawContent; got {session_mock.commit.await_count} commit calls"
    )
    assert row.status == "processed"
    assert isinstance(row.processed_at, datetime)
    assert result["content_id"]


@pytest.mark.asyncio
async def test_create_does_not_commit_when_row_missing() -> None:
    """When RawContent row is not found, no commit happens (no rows to update)."""
    session_factory, session_mock = _make_session_factory(row=None)
    repo = _RawContentResultRepo(session_factory=session_factory)

    await repo.create({"content_id": str(uuid.uuid4()), "tool": "process"})

    assert session_mock.commit.await_count == 0


@pytest.mark.asyncio
async def test_create_does_not_open_session_when_no_content_id() -> None:
    """Early return path: no content_id means no DB interaction."""
    session_factory, session_mock = _make_session_factory(row=None)
    repo = _RawContentResultRepo(session_factory=session_factory)

    await repo.create({"tool": "process"})

    assert session_factory.call_count == 0
