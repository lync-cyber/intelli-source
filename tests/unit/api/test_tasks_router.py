"""Tests for T-083 AC-5 and AC-6: /tasks/collect uses send_task, returns task_id."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from intellisource.api.routers.tasks import router  # type: ignore[import-untyped]
except ImportError:
    router = None  # type: ignore[assignment]

_ROUTER_MISSING = router is None

SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
FAKE_TASK_ID = "celery-task-abc-123"


def _make_task_obj(
    *,
    source_id: uuid.UUID = SOURCE_ID,
    trigger_type: str = "manual",
) -> MagicMock:
    obj = MagicMock()
    obj.id = uuid.UUID("00000000-0000-0000-0000-000000000010")
    obj.source_id = source_id
    obj.task_chain_id = None
    obj.status = "pending"
    obj.priority = "normal"
    obj.trigger_type = trigger_type
    obj.items_collected = 0
    obj.error_message = None
    obj.retry_count = 0
    obj.started_at = None
    obj.finished_at = None
    obj.created_at = "2025-01-01T00:00:00+00:00"
    obj.pipeline_name = "default"
    obj.execution_mode = "strict"
    return obj


def _make_mock_db() -> MagicMock:
    """Return a MagicMock DatabaseManager with a working get_session context manager."""
    mock_session = MagicMock(spec=AsyncSession)

    @asynccontextmanager
    async def _get_session() -> AsyncIterator[MagicMock]:
        yield mock_session

    db = MagicMock()
    db.get_session = _get_session
    db.close = AsyncMock()
    return db


def _make_app_with_celery_state() -> FastAPI:
    """Return a minimal FastAPI app with celery_app and db wired into app.state."""
    if _ROUTER_MISSING:
        pytest.fail(
            "intellisource.api.routers.tasks not implemented: cannot import 'router'"
        )
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")

    mock_celery = MagicMock()
    mock_async_result = MagicMock()
    mock_async_result.id = FAKE_TASK_ID
    mock_celery.send_task = MagicMock(return_value=mock_async_result)

    application.state.celery_app = mock_celery
    application.state.db = _make_mock_db()
    return application


@pytest.fixture()
def app_with_celery() -> FastAPI:
    """FastAPI app with both db and celery_app mocked into app.state."""
    return _make_app_with_celery_state()


@pytest.fixture()
async def celery_client(app_with_celery: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=app_with_celery)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC-5: /tasks/collect triggers send_task("run_pipeline") instead of only DB write
# ---------------------------------------------------------------------------


class TestCollectEndpointSendTask:
    """AC-5: POST /tasks/collect calls send_task on celery_app, returns task_id."""

    @pytest.mark.asyncio
    async def test_collect_calls_send_task(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """AC-5: send_task is invoked on request.app.state.celery_app."""
        mock_repo = AsyncMock()
        mock_repo.create.return_value = _make_task_obj()

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_id": str(SOURCE_ID), "trigger_type": "manual"},
            )

        assert resp.status_code in (200, 202), (
            f"Expected 200 or 202, got {resp.status_code}: {resp.text}"
        )
        app_with_celery.state.celery_app.send_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_response_contains_task_id(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """AC-5: Response body contains a task_id returned by send_task."""
        mock_repo = AsyncMock()
        mock_repo.create.return_value = _make_task_obj()

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_id": str(SOURCE_ID), "trigger_type": "manual"},
            )

        assert resp.status_code in (200, 202)
        body = resp.json()
        assert "task_id" in body, (
            f"Response must contain 'task_id' key, got: {list(body.keys())}"
        )
        assert body["task_id"] == FAKE_TASK_ID


# ---------------------------------------------------------------------------
# AC-6: Unit test — mock send_task, assert called once with source_id in kwargs
# ---------------------------------------------------------------------------


class TestCollectSendTaskKwargs:
    """AC-6: send_task called once; kwargs contain source_id."""

    @pytest.mark.asyncio
    async def test_send_task_called_exactly_once(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """AC-6: send_task is invoked exactly once per /tasks/collect POST."""
        mock_repo = AsyncMock()
        mock_repo.create.return_value = _make_task_obj()

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_id": str(SOURCE_ID), "trigger_type": "manual"},
            )

        call_count = app_with_celery.state.celery_app.send_task.call_count
        assert call_count == 1, (
            f"send_task must be called exactly once, called {call_count} times"
        )

    @pytest.mark.asyncio
    async def test_send_task_kwargs_contain_source_id(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """AC-6: send_task kwargs include source_id matching the request body."""
        mock_repo = AsyncMock()
        mock_repo.create.return_value = _make_task_obj()

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_id": str(SOURCE_ID), "trigger_type": "manual"},
            )

        send_task_mock = app_with_celery.state.celery_app.send_task
        call_args = send_task_mock.call_args

        # task name must be "run_pipeline"
        positional = call_args.args if call_args.args else ()
        if positional:
            assert positional[0] == "run_pipeline", (
                f"send_task first arg must be 'run_pipeline', got {positional[0]!r}"
            )
        else:
            assert call_args.kwargs.get("name") == "run_pipeline" or (
                "run_pipeline" in str(call_args)
            ), f"send_task must target 'run_pipeline', call: {call_args}"

        # kwargs dict passed to send_task must contain source_id
        sent_kwargs = call_args.kwargs.get("kwargs", {})
        if not sent_kwargs and call_args.args and len(call_args.args) > 1:
            sent_kwargs = call_args.args[1]
        assert str(SOURCE_ID) in str(sent_kwargs) or "source_id" in str(sent_kwargs), (
            f"send_task kwargs must include source_id, got: {call_args}"
        )

    @pytest.mark.asyncio
    async def test_send_task_targets_run_pipeline(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """AC-6: send_task is called with task name 'run_pipeline'."""
        mock_repo = AsyncMock()
        mock_repo.create.return_value = _make_task_obj()

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_id": str(SOURCE_ID), "trigger_type": "manual"},
            )

        call_args = app_with_celery.state.celery_app.send_task.call_args
        assert "run_pipeline" in str(call_args), (
            f"Expected 'run_pipeline' in send_task call, got: {call_args}"
        )
