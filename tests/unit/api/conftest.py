"""Unit/API conftest — mock DB on bare FastAPI apps + shared OpenAPI fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
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
    "clusters_app",
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


@pytest.fixture(scope="session")
def main_app() -> FastAPI:
    """Session-cached ``create_app()`` for read-only OpenAPI/route inspection."""
    from intellisource.main import create_app

    return create_app()


@pytest.fixture(scope="session")
def main_openapi(main_app: FastAPI) -> dict[str, Any]:
    """Cached OpenAPI document — avoids rebuilding schema in every test."""
    return main_app.openapi()


@pytest.fixture(scope="session")
def main_openapi_paths(main_openapi: dict[str, Any]) -> dict[str, Any]:
    return main_openapi.get("paths", {})


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
def _patch_api_lifespan_heavy_deps() -> Iterator[None]:
    """Block real Redis / file-watcher side effects in API unit tests.

    ``create_app()`` + ``httpx.ASGITransport`` auto-starts lifespan on the first
    request but most tests never call ``app.shutdown()``. Without this guard,
    ``ConfigWatcher`` (watchfiles on OneDrive) and Redis connect attempts pile
    up and later tests appear to hang.
    """
    mock_redis = AsyncMock()
    with (
        patch(
            "intellisource.main.aioredis.from_url",
            new=AsyncMock(return_value=mock_redis),
        ),
        patch(
            "intellisource.config.loader.ConfigWatcher.start",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "intellisource.config.loader.ConfigWatcher.stop",
            new=AsyncMock(return_value=None),
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _patch_main_database_manager() -> Iterator[MagicMock]:
    """Patch intellisource.main.DatabaseManager for the duration of each test."""
    mock_db_instance = _make_mock_db()
    with patch(
        "intellisource.main.DatabaseManager", return_value=mock_db_instance
    ) as _p:
        yield _p
