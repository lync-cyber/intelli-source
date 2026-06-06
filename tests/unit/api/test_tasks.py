"""Tests for T-041: Task management API endpoints.

Covers:
  AC-062:     API supports manually triggering collection tasks and querying task status
  AC-065:     FastAPI auto-generates OpenAPI documentation
  AC-T041-1:  GET /api/v1/tasks — task list with pagination (cursor-based) and filtering
  AC-T041-2:  POST /api/v1/tasks/collect — trigger collection (returns 202)
  AC-T041-3:  GET /api/v1/tasks/{id} — query single task status
  AC-T041-4:  PATCH /api/v1/tasks/{id} — pause/resume task
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# The router module does not exist yet -- import may fail during RED phase.
try:
    from intellisource.api.routers.tasks import router  # type: ignore[import-untyped]
except ImportError:
    router = None  # type: ignore[assignment]

_ROUTER_MISSING = router is None

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

TASK_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
TASK_ID_2 = uuid.UUID("00000000-0000-0000-0000-000000000011")
SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TASK_CHAIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000020")


def _make_task_obj(
    *,
    id: uuid.UUID = TASK_ID,
    source_id: uuid.UUID = SOURCE_ID,
    task_chain_id: uuid.UUID | None = TASK_CHAIN_ID,
    status: str = "pending",
    priority: str = "normal",
    trigger_type: str = "manual",
    items_collected: int = 0,
    error_message: str | None = None,
    retry_count: int = 0,
) -> MagicMock:
    """Return a MagicMock that mimics a CollectTask ORM instance."""
    obj = MagicMock()
    obj.id = id
    obj.source_id = source_id
    obj.task_chain_id = task_chain_id
    obj.status = status
    obj.priority = priority
    obj.trigger_type = trigger_type
    obj.items_collected = items_collected
    obj.error_message = error_message
    obj.retry_count = retry_count
    obj.started_at = None
    obj.finished_at = None
    obj.created_at = "2025-01-01T00:00:00+00:00"
    return obj


@pytest.fixture()
def app() -> FastAPI:
    """Create a minimal FastAPI app with the tasks router mounted."""
    if _ROUTER_MISSING:
        pytest.fail(
            "intellisource.api.routers.tasks not implemented: cannot import 'router'"
        )
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    return application


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    """Yield an httpx AsyncClient bound to the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


# ===========================================================================
# AC-T041-1: GET /api/v1/tasks — pagination and filtering
# ===========================================================================


class TestTaskListEndpoint:
    """AC-T041-1: GET /api/v1/tasks supports cursor-based pagination and filtering."""

    @pytest.mark.asyncio
    async def test_list_tasks_returns_paginated_result(
        self, client: AsyncClient
    ) -> None:
        """Default GET returns items list with pagination metadata."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [_make_task_obj()],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.get("/api/v1/tasks")

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "next_cursor" in body
        assert "has_more" in body
        assert isinstance(body["items"], list)

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_status(self, client: AsyncClient) -> None:
        """Filtering by status passes the parameter to the repository."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.get("/api/v1/tasks", params={"status": "running"})

        assert resp.status_code == 200
        mock_repo.list.assert_called_once()
        call_kwargs = mock_repo.list.call_args
        assert call_kwargs.kwargs.get("status") == "running" or (
            "running" in str(call_kwargs)
        )

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_source_id(self, client: AsyncClient) -> None:
        """Filtering by source_id passes the parameter to the repository."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.get(
                "/api/v1/tasks", params={"source_id": str(SOURCE_ID)}
            )

        assert resp.status_code == 200
        call_kwargs = mock_repo.list.call_args
        assert str(SOURCE_ID) in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_trigger_type(self, client: AsyncClient) -> None:
        """Filtering by trigger_type passes the parameter to the repository."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.get(
                "/api/v1/tasks", params={"trigger_type": "scheduled"}
            )

        assert resp.status_code == 200
        call_kwargs = mock_repo.list.call_args
        assert call_kwargs.kwargs.get("trigger_type") == "scheduled" or (
            "scheduled" in str(call_kwargs)
        )

    @pytest.mark.asyncio
    async def test_list_tasks_limit_capped_at_100(self, client: AsyncClient) -> None:
        """Limit values above 100 should be capped or rejected."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.get("/api/v1/tasks", params={"limit": 200})

        # Either the router caps limit to 100 (200->OK) or rejects (422).
        if resp.status_code == 200:
            call_kwargs = mock_repo.list.call_args
            actual_limit = call_kwargs.kwargs.get(
                "limit", call_kwargs.args[0] if call_kwargs.args else None
            )
            assert actual_limit is not None and actual_limit <= 100


# ===========================================================================
# AC-T041-2: POST /api/v1/tasks/collect — trigger collection
# ===========================================================================


class TestTaskCollectEndpoint:
    """AC-T041-2: POST /api/v1/tasks/collect triggers collection task."""

    @pytest.mark.asyncio
    async def test_trigger_collect_returns_202(self, client: AsyncClient) -> None:
        """POST /api/v1/tasks/collect with valid source_ids returns 202 Accepted."""
        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = _make_task_obj(trigger_type="manual")
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
            resp = await client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID)]},
            )

        assert resp.status_code == 202

    @pytest.mark.asyncio
    async def test_trigger_collect_returns_task_chain_response(
        self, client: AsyncClient
    ) -> None:
        """Response body contains task_chain_id, tasks list, and message."""
        mock_task_repo = AsyncMock()
        task = _make_task_obj()
        mock_task_repo.create.return_value = task
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
            resp = await client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": [str(SOURCE_ID)]},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert "task_chain_id" in body
        assert "tasks" in body
        assert "message" in body
        assert len(body["tasks"]) == 1
        assert body["tasks"][0]["id"] == str(TASK_ID)

    @pytest.mark.asyncio
    async def test_trigger_collect_invalid_uuid_returns_400(
        self, client: AsyncClient
    ) -> None:
        """Non-UUID string in source_ids returns 400 validation error."""
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
            resp = await client.post(
                "/api/v1/tasks/collect",
                json={"source_ids": ["not-a-uuid"]},
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_trigger_collect_no_source_ids_uses_active_sources(
        self, client: AsyncClient
    ) -> None:
        """Omitting source_ids triggers full sweep using active sources."""
        mock_task_repo = AsyncMock()
        mock_task_repo.create.return_value = _make_task_obj()
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
            resp = await client.post(
                "/api/v1/tasks/collect",
                json={},
            )

        assert resp.status_code == 202
        mock_source_repo.list_active_source_ids.assert_called_once()


# ===========================================================================
# AC-T041-3: GET /api/v1/tasks/{id} — single task detail
# ===========================================================================


class TestTaskDetailEndpoint:
    """AC-T041-3: GET /api/v1/tasks/{id} returns the CollectTask payload.

    Pipeline metadata (pipeline_name / execution_mode) lives on the parent
    TaskChain row; the serializer exposes ``task_chain_id`` so callers can
    follow the link rather than reading non-existent attributes off
    CollectTask (see api/routers/tasks.py _serialize_task).
    """

    @pytest.mark.asyncio
    async def test_get_task_detail_success(self, client: AsyncClient) -> None:
        """GET /api/v1/tasks/{id} returns the task fields plus the
        ``task_chain_id`` link to its parent TaskChain."""
        mock_repo = AsyncMock()
        task = _make_task_obj()
        mock_repo.get_by_id.return_value = task

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.get(f"/api/v1/tasks/{TASK_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(TASK_ID)
        assert body["status"] == "pending"
        assert body["task_chain_id"] == str(TASK_CHAIN_ID)

    @pytest.mark.asyncio
    async def test_get_task_not_found_404(self, client: AsyncClient) -> None:
        """Non-existent task returns 404."""
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None

        nonexistent_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.get(f"/api/v1/tasks/{nonexistent_id}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_task_includes_all_key_fields(self, client: AsyncClient) -> None:
        """Response includes id, source_id, status, trigger_type, items, created_at."""
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = _make_task_obj()

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.get(f"/api/v1/tasks/{TASK_ID}")

        assert resp.status_code == 200
        body = resp.json()
        for field in (
            "id",
            "source_id",
            "status",
            "trigger_type",
            "items_collected",
            "created_at",
        ):
            assert field in body, f"Missing field '{field}' in task detail response"


# ===========================================================================
# AC-T041-4: PATCH /api/v1/tasks/{id} — pause/resume
# ===========================================================================


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


def _app_with_celery(mock_celery: MagicMock) -> FastAPI:
    """Bare tasks-router app with a celery_app + mock db wired into app.state."""
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.state.celery_app = mock_celery
    application.state.db = _make_mock_db()
    return application


class TestTaskUpdateEndpoint:
    """AC-T041-4 / API-009: PATCH /api/v1/tasks/{id} {action} pause/resume/cancel."""

    @pytest.mark.asyncio
    async def test_pause_task_success(self, client: AsyncClient) -> None:
        """action=pause on a running task transitions to paused (200)."""
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = _make_task_obj(status="running")
        mock_repo.update.return_value = _make_task_obj(status="paused")

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.patch(
                f"/api/v1/tasks/{TASK_ID}",
                json={"action": "pause"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "paused"
        assert body["id"] == str(TASK_ID)
        assert "message" in body

    @pytest.mark.asyncio
    async def test_cancel_task_success(self, client: AsyncClient) -> None:
        """action=cancel on a pending task transitions to cancelled (200)."""
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = _make_task_obj(status="pending")
        mock_repo.update.return_value = _make_task_obj(status="cancelled")

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.patch(
                f"/api/v1/tasks/{TASK_ID}",
                json={"action": "cancel"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_illegal_transition_returns_400(self, client: AsyncClient) -> None:
        """action=pause on a pending task is rejected with 400 (not 500)."""
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = _make_task_obj(status="pending")

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.patch(
                f"/api/v1/tasks/{TASK_ID}",
                json={"action": "pause"},
            )

        assert resp.status_code == 400
        mock_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_action_not_found_404(self, client: AsyncClient) -> None:
        """An action on a non-existent task returns 404."""
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None

        nonexistent_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.patch(
                f"/api/v1/tasks/{nonexistent_id}",
                json={"action": "cancel"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_revokes_celery_task_with_terminate(self) -> None:
        """cancel calls control.revoke(celery_task_id, terminate=True)."""
        mock_celery = MagicMock()
        application = _app_with_celery(mock_celery)

        task = _make_task_obj(status="running")
        task.celery_task_id = "celery-xyz"
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = task
        mock_repo.update.return_value = _make_task_obj(status="cancelled")

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_repo,
            ):
                resp = await ac.patch(
                    f"/api/v1/tasks/{TASK_ID}", json={"action": "cancel"}
                )

        assert resp.status_code == 200
        mock_celery.control.revoke.assert_called_once()
        call = mock_celery.control.revoke.call_args
        assert call.args[0] == "celery-xyz"
        assert call.kwargs.get("terminate") is True

    @pytest.mark.asyncio
    async def test_pause_revokes_with_terminate(self) -> None:
        """pause terminates the running task (revoke w/o terminate wouldn't stop
        a running run); resumability comes from resume's idempotent re-dispatch,
        not from leaving the run alive."""
        mock_celery = MagicMock()
        application = _app_with_celery(mock_celery)

        task = _make_task_obj(status="running")
        task.celery_task_id = "celery-abc"
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = task
        mock_repo.update.return_value = _make_task_obj(status="paused")

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch(
                "intellisource.api.routers.tasks.TaskRepository",
                return_value=mock_repo,
            ):
                resp = await ac.patch(
                    f"/api/v1/tasks/{TASK_ID}", json={"action": "pause"}
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"
        call = mock_celery.control.revoke.call_args
        assert call.args[0] == "celery-abc"
        assert call.kwargs.get("terminate") is True

    @pytest.mark.asyncio
    async def test_resume_redispatches_pipeline_with_force(self) -> None:
        """resume re-dispatches run_pipeline (force=True) and stores the new id."""
        mock_celery = MagicMock()
        mock_celery.send_task = MagicMock(return_value=MagicMock(id="new-celery-id"))
        application = _app_with_celery(mock_celery)

        task = _make_task_obj(status="paused")
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = task
        mock_repo.update.return_value = _make_task_obj(status="running")
        mock_source_repo = AsyncMock()
        mock_source_repo.get_types_by_ids.return_value = {SOURCE_ID: "rss"}

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with (
                patch(
                    "intellisource.api.routers.tasks.TaskRepository",
                    return_value=mock_repo,
                ),
                patch(
                    "intellisource.api.routers.tasks.SourceRepository",
                    return_value=mock_source_repo,
                ),
            ):
                resp = await ac.patch(
                    f"/api/v1/tasks/{TASK_ID}", json={"action": "resume"}
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        mock_celery.send_task.assert_called_once()
        sent_kwargs = mock_celery.send_task.call_args.kwargs["kwargs"]
        assert sent_kwargs["pipeline_name"] in ("scheduled-collect", "manual-collect")
        assert sent_kwargs["params"]["force"] is True
        update_call = mock_repo.update.call_args
        assert update_call.kwargs["celery_task_id"] == "new-celery-id"

    @pytest.mark.asyncio
    async def test_resume_without_celery_returns_503(self, client: AsyncClient) -> None:
        """resume when celery_app is unwired returns 503 (no silent no-op)."""
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = _make_task_obj(status="paused")

        with patch(
            "intellisource.api.routers.tasks.TaskRepository",
            return_value=mock_repo,
        ):
            resp = await client.patch(
                f"/api/v1/tasks/{TASK_ID}",
                json={"action": "resume"},
            )

        assert resp.status_code == 503


# ===========================================================================
# AC-065: OpenAPI documentation (task endpoints)
# ===========================================================================


class TestOpenApiDocs:
    """AC-065: FastAPI auto-generates OpenAPI documentation for task endpoints."""

    @pytest.mark.asyncio
    async def test_openapi_json_accessible(self, client: AsyncClient) -> None:
        """The /openapi.json endpoint is accessible and contains paths."""
        resp = await client.get("/openapi.json")

        assert resp.status_code == 200
        body = resp.json()
        assert "paths" in body
        assert "/api/v1/tasks" in body["paths"]

    @pytest.mark.asyncio
    async def test_openapi_contains_task_operations(self, client: AsyncClient) -> None:
        """OpenAPI spec documents GET for tasks and POST for collect."""
        resp = await client.get("/openapi.json")

        assert resp.status_code == 200
        body = resp.json()
        tasks_path = body["paths"].get("/api/v1/tasks", {})
        assert "get" in tasks_path, "GET /api/v1/tasks not documented"

        collect_path = body["paths"].get("/api/v1/tasks/collect", {})
        assert "post" in collect_path, "POST /api/v1/tasks/collect not documented"

        task_id_path = body["paths"].get("/api/v1/tasks/{id}", {})
        assert "get" in task_id_path, "GET /api/v1/tasks/{id} not documented"
        assert "patch" in task_id_path, "PATCH /api/v1/tasks/{id} not documented"
