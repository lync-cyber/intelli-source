"""T-095 RED AC-8: send_task kwargs contract on POST /tasks/collect.

Verifies that /tasks/collect calls celery.send_task("run_pipeline", kwargs=...)
with the new contract:
- kwargs MUST contain top-level key 'pipeline_name' (e.g. "scheduled-collect")
- kwargs MUST contain top-level key 'params' (a dict)
- params dict MUST contain task_id, source_id (and ideally task_chain_id,
  trigger_type, priority, fingerprint)

The current implementation (api/routers/tasks.py:154-162) ships kwargs flat:
    {"source_id": ..., "task_id": ..., "task_chain_id": ..., "priority": ...}
and is missing pipeline_name entirely — so these tests must FAIL on main.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
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
FAKE_TASK_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


def _make_task_obj() -> MagicMock:
    obj = MagicMock()
    obj.id = FAKE_TASK_ID
    obj.source_id = SOURCE_ID
    obj.task_chain_id = None
    obj.status = "pending"
    obj.priority = "normal"
    obj.trigger_type = "manual"
    obj.items_collected = 0
    obj.error_message = None
    obj.retry_count = 0
    obj.started_at = None
    obj.finished_at = None
    obj.created_at = "2025-01-01T00:00:00+00:00"
    obj.pipeline_name = "scheduled-collect"
    obj.execution_mode = "strict"
    return obj


def _make_mock_db() -> MagicMock:
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
            "intellisource.api.routers.tasks not importable — cannot run AC-8 tests"
        )
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")

    mock_celery = MagicMock()
    mock_celery.send_task = MagicMock(return_value=MagicMock(id="celery-task-id"))

    application.state.celery_app = mock_celery
    application.state.db = _make_mock_db()
    return application


@pytest.fixture()
def app_with_celery() -> FastAPI:
    return _make_app_with_celery_state()


@pytest.fixture()
async def celery_client(app_with_celery: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=app_with_celery)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


def _patched_repos(source_type: str = "rss") -> Any:
    """Context manager bundle: patch SourceRepository + TaskRepository."""
    mock_task_repo = AsyncMock()
    mock_task_repo.create.return_value = _make_task_obj()
    mock_source_repo = AsyncMock()
    mock_source_repo.list_active_source_ids.return_value = [SOURCE_ID]
    mock_source_repo.get_types_by_ids.return_value = {SOURCE_ID: source_type}
    return mock_task_repo, mock_source_repo


# ---------------------------------------------------------------------------
# AC-8: send_task kwargs contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_task_kwargs_contains_pipeline_name(
    celery_client: AsyncClient, app_with_celery: FastAPI
) -> None:
    """AC-8: send_task kwargs must include top-level 'pipeline_name'."""
    mock_task_repo, mock_source_repo = _patched_repos()
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
            "/api/v1/tasks/collect", json={"priority": "normal"}
        )

    assert resp.status_code == 202, resp.text
    send_task_mock = app_with_celery.state.celery_app.send_task
    assert send_task_mock.call_count >= 1, "send_task was not called"
    sent_kwargs = send_task_mock.call_args.kwargs["kwargs"]
    assert "pipeline_name" in sent_kwargs, (
        f"AC-8: send_task kwargs missing 'pipeline_name'; got keys: {list(sent_kwargs)}"
    )
    assert sent_kwargs["pipeline_name"] in ("scheduled-collect", "manual-collect"), (
        f"AC-8: pipeline_name must be a real pipeline yaml name; "
        f"got: {sent_kwargs['pipeline_name']!r}"
    )


@pytest.mark.asyncio
async def test_send_task_kwargs_contains_params_dict(
    celery_client: AsyncClient, app_with_celery: FastAPI
) -> None:
    """AC-8: send_task kwargs must include 'params' as a nested dict."""
    mock_task_repo, mock_source_repo = _patched_repos()
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
            "/api/v1/tasks/collect", json={"priority": "normal"}
        )

    assert resp.status_code == 202, resp.text
    sent_kwargs = app_with_celery.state.celery_app.send_task.call_args.kwargs["kwargs"]
    assert "params" in sent_kwargs, (
        f"AC-8: send_task kwargs missing 'params'; got keys: {list(sent_kwargs)}"
    )
    assert isinstance(sent_kwargs["params"], dict), (
        f"AC-8: 'params' must be a dict; got {type(sent_kwargs['params'])}"
    )


@pytest.mark.asyncio
async def test_send_task_params_contains_task_id_and_source_id(
    celery_client: AsyncClient, app_with_celery: FastAPI
) -> None:
    """AC-8: params.task_id and params.source_id are set."""
    mock_task_repo, mock_source_repo = _patched_repos()
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
            "/api/v1/tasks/collect", json={"priority": "normal"}
        )

    assert resp.status_code == 202, resp.text
    sent_kwargs = app_with_celery.state.celery_app.send_task.call_args.kwargs["kwargs"]
    params = sent_kwargs.get("params", {})
    assert params.get("task_id") == str(FAKE_TASK_ID), (
        f"AC-8: params.task_id must equal the created task id; "
        f"got: {params.get('task_id')!r}"
    )
    assert params.get("source_id") == str(SOURCE_ID), (
        f"AC-8: params.source_id must equal the source id; "
        f"got: {params.get('source_id')!r}"
    )


@pytest.mark.asyncio
async def test_send_task_kwargs_no_longer_flat(
    celery_client: AsyncClient, app_with_celery: FastAPI
) -> None:
    """AC-8: legacy flat kwargs (source_id/task_id/task_chain_id at top-level)
    should NOT be present alongside the new contract (they belong under 'params').

    The new contract is exclusive: top-level keys are {pipeline_name, params}
    only. Flat top-level source_id/task_id is the legacy shape — its presence
    indicates the migration is incomplete.
    """
    mock_task_repo, mock_source_repo = _patched_repos()
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
            "/api/v1/tasks/collect", json={"priority": "normal"}
        )

    assert resp.status_code == 202, resp.text
    sent_kwargs = app_with_celery.state.celery_app.send_task.call_args.kwargs["kwargs"]
    top_keys = set(sent_kwargs.keys())
    legacy_top_level = {"source_id", "task_id", "task_chain_id"} & top_keys
    assert not legacy_top_level, (
        f"AC-8: legacy flat kwargs still present at top level: {legacy_top_level}; "
        f"these belong under 'params'"
    )


# ---------------------------------------------------------------------------
# r2 R-001: source_type → pipeline_name routes via real Source.type lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_task_pipeline_name_routes_by_source_type(
    celery_client: AsyncClient,
    app_with_celery: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """r2 R-001: when SOURCE_TYPE_TO_PIPELINE has differentiated entries,
    /tasks/collect must look up Source.type via SourceRepository.get_types_by_ids
    and route to the matching pipeline — not silently fall back to "rss"."""
    from intellisource.composition import SOURCE_TYPE_TO_PIPELINE

    # Inject a differentiated mapping so "web" routes to a distinct pipeline.
    monkeypatch.setitem(SOURCE_TYPE_TO_PIPELINE, "web", "web-collect")

    mock_task_repo, mock_source_repo = _patched_repos(source_type="web")
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
            "/api/v1/tasks/collect", json={"priority": "normal"}
        )

    assert resp.status_code == 202, resp.text
    sent_kwargs = app_with_celery.state.celery_app.send_task.call_args.kwargs["kwargs"]
    assert sent_kwargs["pipeline_name"] == "web-collect", (
        f"r2 R-001: pipeline_name must be resolved via Source.type lookup "
        f"('web' → 'web-collect'); got {sent_kwargs['pipeline_name']!r}. "
        f"This is the EXP-005-shaped 'wired-but-inert' failure."
    )
    mock_source_repo.get_types_by_ids.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_task_pipeline_name_falls_back_when_source_missing(
    celery_client: AsyncClient, app_with_celery: FastAPI
) -> None:
    """r2 R-001: when Source.type lookup returns no row (race / stale ID),
    fall back to "scheduled-collect" rather than crashing."""
    mock_task_repo = AsyncMock()
    mock_task_repo.create.return_value = _make_task_obj()
    mock_source_repo = AsyncMock()
    mock_source_repo.list_active_source_ids.return_value = [SOURCE_ID]
    mock_source_repo.get_types_by_ids.return_value = {}  # empty — row missing

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
            "/api/v1/tasks/collect", json={"priority": "normal"}
        )

    assert resp.status_code == 202, resp.text
    sent_kwargs = app_with_celery.state.celery_app.send_task.call_args.kwargs["kwargs"]
    assert sent_kwargs["pipeline_name"] == "scheduled-collect"


# ---------------------------------------------------------------------------
# F-26: priority → queue routing (send_task queue= argument + enum validation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "priority,expected_queue",
    [
        ("low", "queue.priority.low"),
        ("normal", "queue.priority.normal"),
        ("high", "queue.priority.high"),
    ],
)
async def test_send_task_routes_to_priority_queue(
    celery_client: AsyncClient,
    app_with_celery: FastAPI,
    priority: str,
    expected_queue: str,
) -> None:
    """F-26: send_task must include queue=PRIORITY_QUEUES[priority]."""
    mock_task_repo, mock_source_repo = _patched_repos()
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
            "/api/v1/tasks/collect", json={"priority": priority}
        )

    assert resp.status_code == 202, resp.text
    call_kwargs = app_with_celery.state.celery_app.send_task.call_args.kwargs
    assert call_kwargs.get("queue") == expected_queue, (
        f"F-26: priority={priority} must route to queue={expected_queue!r}; "
        f"got queue={call_kwargs.get('queue')!r}"
    )


@pytest.mark.asyncio
async def test_send_task_forwards_trace_id_in_headers(
    celery_client: AsyncClient, app_with_celery: FastAPI
) -> None:
    """F-23: send_task must include headers={trace_id: ...} from request ctx."""
    from intellisource.observability.trace_context import (
        TRACE_HEADER_KEY,
        trace_id_ctx,
    )

    mock_task_repo, mock_source_repo = _patched_repos()
    token = trace_id_ctx.set("trace-router-001")
    try:
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
                "/api/v1/tasks/collect", json={"priority": "normal"}
            )
    finally:
        trace_id_ctx.reset(token)

    assert resp.status_code == 202, resp.text
    call_kwargs = app_with_celery.state.celery_app.send_task.call_args.kwargs
    headers = call_kwargs.get("headers", {})
    assert TRACE_HEADER_KEY in headers, (
        f"F-23: send_task must forward trace_id via headers; got headers={headers!r}"
    )


@pytest.mark.asyncio
async def test_invalid_priority_rejected_with_400(
    celery_client: AsyncClient, app_with_celery: FastAPI
) -> None:
    """F-26: priority outside {low,normal,high} returns 400 (not silently routed)."""
    mock_task_repo, mock_source_repo = _patched_repos()
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
            "/api/v1/tasks/collect", json={"priority": "urgent"}
        )

    assert resp.status_code == 400, resp.text
    assert "urgent" in resp.text or "priority" in resp.text
    # send_task must not have fired with an invalid priority
    assert app_with_celery.state.celery_app.send_task.call_count == 0
