"""Tests for POST /tasks/collect endpoint (AC-5, AC-6, API-007 schema)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
SOURCE_ID_2 = uuid.UUID("00000000-0000-0000-0000-000000000002")
FAKE_TASK_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
FAKE_TASK_ID_2 = uuid.UUID("00000000-0000-0000-0000-000000000011")


def _make_task_obj(
    *,
    task_id: uuid.UUID = FAKE_TASK_ID,
    source_id: uuid.UUID = SOURCE_ID,
    trigger_type: str = "manual",
    task_chain_id: uuid.UUID | None = None,
) -> MagicMock:
    obj = MagicMock()
    obj.id = task_id
    obj.source_id = source_id
    obj.task_chain_id = task_chain_id
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
# AC-5 / API-007: single source_id scenario
# ---------------------------------------------------------------------------


class TestCollectSingleSource:
    """POST /tasks/collect with a single source_id in the list."""

    @pytest.mark.asyncio
    async def test_single_source_returns_202(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """Single source_ids entry returns 202 with task_chain_id, tasks, message."""
        task_obj = _make_task_obj()
        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = task_obj
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID)], "priority": "normal"},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert "task_chain_id" in body
        assert "tasks" in body
        assert "message" in body
        assert len(body["tasks"]) == 1
        assert body["tasks"][0]["id"] == str(FAKE_TASK_ID)
        assert body["tasks"][0]["type"] == "collect"
        assert body["tasks"][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_single_source_calls_send_task_once(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """AC-5: send_task is invoked exactly once for a single source_id."""
        task_obj = _make_task_obj()
        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = task_obj
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID)]},
            )

        assert app_with_celery.state.celery_app.send_task.call_count == 1

    @pytest.mark.asyncio
    async def test_single_source_send_task_exact_kwargs(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """AC-6: send_task is called with 'run_pipeline' and exact kwargs structure."""
        task_obj = _make_task_obj()
        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = task_obj
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID)], "priority": "normal"},
            )

        send_task_mock = app_with_celery.state.celery_app.send_task
        call_args = send_task_mock.call_args
        assert call_args.args[0] == "run_pipeline"
        # T-095 contract: kwargs = {pipeline_name, params: {...}}
        sent_kwargs = call_args.kwargs["kwargs"]
        assert "pipeline_name" in sent_kwargs
        params = sent_kwargs["params"]
        assert params["source_id"] == str(SOURCE_ID)
        assert params["task_id"] == str(FAKE_TASK_ID)
        assert "task_chain_id" in params
        assert params["priority"] == "normal"


# ---------------------------------------------------------------------------
# Multiple source_ids scenario
# ---------------------------------------------------------------------------


class TestCollectMultipleSources:
    """POST /tasks/collect with multiple source_ids."""

    @pytest.mark.asyncio
    async def test_multiple_sources_creates_multiple_tasks(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """Two source_ids → two tasks in response, send_task called twice."""
        task_obj_1 = _make_task_obj(task_id=FAKE_TASK_ID, source_id=SOURCE_ID)
        task_obj_2 = _make_task_obj(task_id=FAKE_TASK_ID_2, source_id=SOURCE_ID_2)
        mock_task_repo = AsyncMock()
        mock_task_repo.create.side_effect = [task_obj_1, task_obj_2]
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID), str(SOURCE_ID_2)]},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert len(body["tasks"]) == 2
        task_ids = {t["id"] for t in body["tasks"]}
        assert str(FAKE_TASK_ID) in task_ids
        assert str(FAKE_TASK_ID_2) in task_ids
        assert app_with_celery.state.celery_app.send_task.call_count == 2

    @pytest.mark.asyncio
    async def test_multiple_sources_share_task_chain_id(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """All tasks created in one request share the same task_chain_id."""
        task_obj_1 = _make_task_obj(task_id=FAKE_TASK_ID, source_id=SOURCE_ID)
        task_obj_2 = _make_task_obj(task_id=FAKE_TASK_ID_2, source_id=SOURCE_ID_2)
        mock_task_repo = AsyncMock()
        mock_task_repo.create.side_effect = [task_obj_1, task_obj_2]
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID), str(SOURCE_ID_2)]},
            )

        body = resp.json()
        chain_id = body["task_chain_id"]
        assert uuid.UUID(chain_id)  # valid UUID

        calls = app_with_celery.state.celery_app.send_task.call_args_list
        for call in calls:
            # T-095 contract: chain id lives under params, not at top level
            assert call.kwargs["kwargs"]["params"]["task_chain_id"] == chain_id

    @pytest.mark.asyncio
    async def test_multiple_sources_message_contains_count(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """Response message reflects the number of tasks created."""
        task_obj_1 = _make_task_obj(task_id=FAKE_TASK_ID, source_id=SOURCE_ID)
        task_obj_2 = _make_task_obj(task_id=FAKE_TASK_ID_2, source_id=SOURCE_ID_2)
        mock_task_repo = AsyncMock()
        mock_task_repo.create.side_effect = [task_obj_1, task_obj_2]
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID), str(SOURCE_ID_2)]},
            )

        body = resp.json()
        assert "2" in body["message"]


# ---------------------------------------------------------------------------
# source_ids=None or empty → full active-source sweep
# ---------------------------------------------------------------------------


class TestCollectAllActiveSources:
    """source_ids=None or [] triggers full sweep of active sources."""

    @pytest.mark.asyncio
    async def test_no_source_ids_fetches_active_sources(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """Omitting source_ids calls list_active_source_ids and creates N tasks."""
        task_obj_1 = _make_task_obj(task_id=FAKE_TASK_ID, source_id=SOURCE_ID)
        task_obj_2 = _make_task_obj(task_id=FAKE_TASK_ID_2, source_id=SOURCE_ID_2)
        mock_task_repo = AsyncMock()
        mock_task_repo.create.side_effect = [task_obj_1, task_obj_2]
        mock_source_repo = AsyncMock()
        mock_source_repo.list_active_source_ids.return_value = [SOURCE_ID, SOURCE_ID_2]

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={},
            )

        assert resp.status_code == 202
        mock_source_repo.list_active_source_ids.assert_called_once()
        body = resp.json()
        assert len(body["tasks"]) == 2
        assert app_with_celery.state.celery_app.send_task.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_source_ids_fetches_active_sources(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """source_ids=[] also triggers active-source sweep (same as omitting)."""
        task_obj = _make_task_obj()
        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = task_obj
        mock_source_repo = AsyncMock()
        mock_source_repo.list_active_source_ids.return_value = [SOURCE_ID]

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": []},
            )

        assert resp.status_code == 202
        mock_source_repo.list_active_source_ids.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_active_sources_returns_202_empty_tasks(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """When no active sources exist, returns 202 with empty tasks list."""
        mock_task_repo = AsyncMock()
        mock_source_repo = AsyncMock()
        mock_source_repo.list_active_source_ids.return_value = []

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert body["tasks"] == []
        assert "task_chain_id" in body
        assert "message" in body
        app_with_celery.state.celery_app.send_task.assert_not_called()


# ---------------------------------------------------------------------------
# Error handling: invalid source_ids
# ---------------------------------------------------------------------------


class TestCollectInvalidSourceIds:
    """Invalid source_id values return 400."""

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_400(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """Non-UUID string in source_ids returns 400 with detail."""
        mock_task_repo = AsyncMock()
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": ["not-a-uuid"]},
            )

        assert resp.status_code == 400
        body = resp.json()
        assert "invalid source_ids" in body["detail"]

    @pytest.mark.asyncio
    async def test_mixed_valid_invalid_returns_400(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """Mix of valid and invalid UUIDs returns 400 listing only the invalid ones."""
        mock_task_repo = AsyncMock()
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID), "bad-id"]},
            )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# AC-6 precision: send_task exact argument verification
# ---------------------------------------------------------------------------


class TestCollectSendTaskPrecision:
    """Precise assertion on send_task arguments (R-006 resolution)."""

    @pytest.mark.asyncio
    async def test_send_task_first_arg_is_run_pipeline(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """send_task positional arg[0] is exactly 'run_pipeline'."""
        task_obj = _make_task_obj()
        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = task_obj
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID)]},
            )

        call_args = app_with_celery.state.celery_app.send_task.call_args
        assert call_args.args[0] == "run_pipeline"

    @pytest.mark.asyncio
    async def test_send_task_kwargs_source_id_exact(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """send_task kwargs['source_id'] is the string form of SOURCE_ID."""
        task_obj = _make_task_obj()
        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = task_obj
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID)]},
            )

        call_args = app_with_celery.state.celery_app.send_task.call_args
        sent_kwargs = call_args.kwargs["kwargs"]
        # T-095 contract: source_id is nested under params
        assert sent_kwargs["params"]["source_id"] == str(SOURCE_ID)

    @pytest.mark.asyncio
    async def test_send_task_kwargs_task_id_exact(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """send_task kwargs['task_id'] is the string form of the created task's id."""
        task_obj = _make_task_obj()
        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = task_obj
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID)]},
            )

        call_args = app_with_celery.state.celery_app.send_task.call_args
        sent_kwargs = call_args.kwargs["kwargs"]
        # T-095 contract: task_id is nested under params
        assert sent_kwargs["params"]["task_id"] == str(FAKE_TASK_ID)

    @pytest.mark.asyncio
    async def test_send_task_kwargs_priority_exact(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """send_task kwargs['priority'] matches the request priority."""
        task_obj = _make_task_obj()
        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = task_obj
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID)], "priority": "high"},
            )

        call_args = app_with_celery.state.celery_app.send_task.call_args
        sent_kwargs = call_args.kwargs["kwargs"]
        # T-095 contract: priority is nested under params
        assert sent_kwargs["params"]["priority"] == "high"


# ---------------------------------------------------------------------------
# R-007 regression: datetime serialization in response body
# ---------------------------------------------------------------------------


class TestCollectDatetimeSerialization:
    """Regression guard: real datetime objects in task fields must not cause 500."""

    @pytest.mark.asyncio
    async def test_collect_serializes_datetime_in_response_body(
        self, celery_client: AsyncClient, app_with_celery: FastAPI
    ) -> None:
        """created_at as a real datetime is serialized to ISO string in the 202 body."""
        real_dt = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
        task_obj = _make_task_obj()
        task_obj.created_at = real_dt

        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = task_obj
        mock_source_repo = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_task_repo,
            ),
            patch(
                "intellisource.api.routers.tasks.SourceRepository",
                return_value=mock_source_repo,
            ),
        ):
            resp = await celery_client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID)], "priority": "normal"},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert len(body["tasks"]) == 1
        created_at_value = body["tasks"][0]["created_at"]
        assert isinstance(created_at_value, str)
        assert "2026-05-21" in created_at_value
