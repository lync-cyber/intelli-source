"""Unit/API conftest — injects a mock DatabaseManager into bare FastAPI test apps.

Router unit tests create plain FastAPI() apps without lifespan, so app.state.db
is never populated by a startup handler.  This fixture sets a mock DatabaseManager
on every app fixture used in this directory so that get_db_session() can delegate
to app.state.db.get_session() without raising AttributeError.

A second autouse fixture patches intellisource.main.DatabaseManager so that tests
which call create_app() and trigger the lifespan (e.g. test_app_entry.py) do not
fail with ValueError when IS_DATABASE_URL is not set.

Tests that patch DatabaseManager themselves (test_lifespan.py, test_deps_integration.py)
apply an inner patch that temporarily overrides this outer fixture's patch for the
duration of that test's patch context.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

_APP_FIXTURE_NAMES = (
    "app",
    "contents_app",
    "search_app",
    "subscriptions_app",
    "llm_app",
    "system_app",
)


def _make_mock_db() -> MagicMock:
    """Return a MagicMock DatabaseManager whose get_session yields a mock session."""
    mock_session = MagicMock(spec=AsyncSession)

    @asynccontextmanager
    async def _get_session() -> AsyncIterator[MagicMock]:
        yield mock_session

    db = MagicMock()
    db.get_session = _get_session
    db.close = AsyncMock()
    return db


@pytest.fixture(autouse=True)
def _inject_mock_db_into_app_fixtures(request: pytest.FixtureRequest) -> None:
    """Set app.state.db on every FastAPI app fixture found in the current test."""
    for name in _APP_FIXTURE_NAMES:
        if name not in request.fixturenames:
            continue
        app_instance = request.getfixturevalue(name)
        if isinstance(app_instance, FastAPI) and not hasattr(app_instance.state, "db"):
            app_instance.state.db = _make_mock_db()


@pytest.fixture(autouse=True)
def _patch_main_database_manager() -> AsyncIterator[None]:  # type: ignore[misc]
    """Patch intellisource.main.DatabaseManager for the duration of each test.

    Tests in test_app_entry.py call create_app() and trigger the lifespan via
    httpx.ASGITransport without patching DatabaseManager themselves.  This outer
    fixture ensures DatabaseManager() never raises ValueError when IS_DATABASE_URL
    is absent.  Inner per-test patches (test_lifespan.py) override this via the
    normal unittest.mock patch nesting semantics.
    """
    mock_db_instance = _make_mock_db()
    with patch(
        "intellisource.main.DatabaseManager", return_value=mock_db_instance
    ) as _p:
        yield _p
