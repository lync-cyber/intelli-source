"""Inc3: GET /tasks/chains/{id} — task chain detail."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.routers.tasks import router

CHAIN_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def _make_mock_db() -> MagicMock:
    mock_session = MagicMock(spec=AsyncSession)

    @asynccontextmanager
    async def _get_session() -> AsyncIterator[MagicMock]:
        yield mock_session

    db = MagicMock()
    db.get_session = _get_session
    return db


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.db = _make_mock_db()
    return app


def _make_chain() -> MagicMock:
    chain = MagicMock()
    chain.id = CHAIN_ID
    chain.pipeline_name = "manual-collect"
    chain.status = "running"
    chain.trigger_type = "manual"
    chain.execution_mode = "parallel"
    chain.total_steps = 5
    chain.completed_steps = 2
    chain.current_step = "process"
    chain.error_message = None
    chain.started_at = None
    chain.finished_at = None
    chain.created_at = "2026-01-01T00:00:00+00:00"
    return chain


@pytest.mark.asyncio
async def test_get_task_chain_returns_detail() -> None:
    from unittest.mock import AsyncMock

    mock_repo = AsyncMock()
    mock_repo.get.return_value = _make_chain()

    app = _build_app()
    with patch(
        "intellisource.api.routers.tasks.TaskChainRepository", return_value=mock_repo
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/v1/tasks/chains/{CHAIN_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(CHAIN_ID)
    assert body["pipeline_name"] == "manual-collect"
    assert body["status"] == "running"
    assert body["total_steps"] == 5
    assert body["completed_steps"] == 2
    assert body["current_step"] == "process"
    mock_repo.get.assert_awaited_once_with(str(CHAIN_ID))


@pytest.mark.asyncio
async def test_get_task_chain_404_when_absent() -> None:
    from unittest.mock import AsyncMock

    mock_repo = AsyncMock()
    mock_repo.get.return_value = None

    app = _build_app()
    with patch(
        "intellisource.api.routers.tasks.TaskChainRepository", return_value=mock_repo
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/v1/tasks/chains/{CHAIN_ID}")

    assert resp.status_code == 404
    assert resp.json()["error"]["message"] == "not found"
