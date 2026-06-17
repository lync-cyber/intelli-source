"""POST /tasks/collect must fast-fail with 503 when the broker is down.

When task dispatch raises BrokerUnavailableError, the endpoint returns 503 and
the just-created task rows are rolled back (the request session never commits).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from kombu.exceptions import OperationalError as KombuOperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.routers.tasks import router

SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
FAKE_TASK_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


def _make_task_obj() -> MagicMock:
    obj = MagicMock()
    obj.id = FAKE_TASK_ID
    obj.source_id = SOURCE_ID
    obj.task_chain_id = None
    obj.status = "pending"
    obj.priority = "normal"
    obj.trigger_type = "manual"
    obj.created_at = "2025-01-01T00:00:00+00:00"
    obj.pipeline_name = "scheduled-collect"
    obj.execution_mode = "strict"
    return obj


def _make_rollback_aware_db() -> tuple[MagicMock, MagicMock]:
    """Return (db, session) where get_session mirrors real commit/rollback."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    @asynccontextmanager
    async def _get_session() -> AsyncIterator[MagicMock]:
        try:
            yield mock_session
            await mock_session.commit()
        except Exception:
            await mock_session.rollback()
            raise
        finally:
            await mock_session.close()

    db = MagicMock()
    db.get_session = _get_session
    return db, mock_session


def _make_app(send_task: MagicMock) -> tuple[FastAPI, MagicMock]:
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    mock_celery = MagicMock()
    mock_celery.send_task = send_task
    application.state.celery_app = mock_celery
    db, session = _make_rollback_aware_db()
    application.state.db = db
    return application, session


def _patched_repos() -> tuple[AsyncMock, AsyncMock]:
    mock_task_repo = AsyncMock()
    mock_task_repo.create.return_value = _make_task_obj()
    mock_source_repo = AsyncMock()
    mock_source_repo.list_active_source_ids.return_value = [SOURCE_ID]
    mock_source_repo.get_types_by_ids.return_value = {SOURCE_ID: "rss"}
    return mock_task_repo, mock_source_repo


@pytest.mark.asyncio
async def test_collect_returns_503_when_broker_unavailable() -> None:
    send_task = MagicMock(side_effect=KombuOperationalError("broker down"))
    app, _session = _make_app(send_task)
    task_repo, source_repo = _patched_repos()
    with (
        patch("intellisource.api.routers.tasks.TaskRepository", return_value=task_repo),
        patch(
            "intellisource.api.routers.tasks.SourceRepository",
            return_value=source_repo,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/tasks/collect", json={"priority": "normal"})

    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_collect_rolls_back_task_rows_when_broker_unavailable() -> None:
    """503 path must roll back (not commit) the just-created task rows."""
    send_task = MagicMock(side_effect=KombuOperationalError("broker down"))
    app, session = _make_app(send_task)
    task_repo, source_repo = _patched_repos()
    with (
        patch("intellisource.api.routers.tasks.TaskRepository", return_value=task_repo),
        patch(
            "intellisource.api.routers.tasks.SourceRepository",
            return_value=source_repo,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/tasks/collect", json={"priority": "normal"})

    assert resp.status_code == 503, resp.text
    session.rollback.assert_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_collect_succeeds_with_202_when_broker_up() -> None:
    """Control: healthy broker still returns 202 and commits."""
    send_task = MagicMock(return_value=MagicMock(id="celery-task-id"))
    app, session = _make_app(send_task)
    task_repo, source_repo = _patched_repos()
    with (
        patch("intellisource.api.routers.tasks.TaskRepository", return_value=task_repo),
        patch(
            "intellisource.api.routers.tasks.SourceRepository",
            return_value=source_repo,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/tasks/collect", json={"priority": "normal"})

    assert resp.status_code == 202, resp.text
    session.commit.assert_awaited()
    session.rollback.assert_not_awaited()
