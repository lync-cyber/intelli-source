"""P0-2 关联收尾: GET /api/v1/tasks/celery/{task_id} wraps Celery AsyncResult.

run_pipeline / trigger_pipeline dispatch returns a raw Celery task id; this
endpoint lets a caller holding only that id poll broker-side state and fetch the
result, distinct from /tasks/chains/{id} (which reads the TaskChain DB row).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.routers import tasks as tasks_module
from intellisource.api.routers.tasks import router as tasks_router


@pytest.fixture()
def celery_app_obj() -> FastAPI:
    app = FastAPI()
    app.include_router(tasks_router, prefix="/api/v1")
    app.state.celery_app = object()
    return app


class _FakeAsyncResult:
    def __init__(self, state: str, ready: bool, successful: bool, result: Any) -> None:
        self._state = state
        self._ready = ready
        self._successful = successful
        self._result = result

    @property
    def state(self) -> str:
        return self._state

    def ready(self) -> bool:
        return self._ready

    def successful(self) -> bool:
        return self._successful

    @property
    def result(self) -> Any:
        return self._result


@pytest.mark.asyncio
async def test_celery_task_success_returns_state_and_result(
    celery_app_obj: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tasks_module,
        "AsyncResult",
        lambda task_id, app=None: _FakeAsyncResult("SUCCESS", True, True, {"sent": 5}),
    )
    async with AsyncClient(
        transport=ASGITransport(app=celery_app_obj), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/tasks/celery/abc-123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == "abc-123"
    assert body["state"] == "SUCCESS"
    assert body["ready"] is True
    assert body["successful"] is True
    assert body["result"] == {"sent": 5}


@pytest.mark.asyncio
async def test_celery_task_pending_has_no_result(
    celery_app_obj: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tasks_module,
        "AsyncResult",
        lambda task_id, app=None: _FakeAsyncResult("PENDING", False, False, None),
    )
    async with AsyncClient(
        transport=ASGITransport(app=celery_app_obj), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/tasks/celery/pending-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "PENDING"
    assert body["ready"] is False
    assert "result" not in body


@pytest.mark.asyncio
async def test_celery_task_failure_surfaces_error(
    celery_app_obj: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tasks_module,
        "AsyncResult",
        lambda task_id, app=None: _FakeAsyncResult(
            "FAILURE", True, False, RuntimeError("boom")
        ),
    )
    async with AsyncClient(
        transport=ASGITransport(app=celery_app_obj), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/tasks/celery/failed-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "FAILURE"
    assert body["successful"] is False
    assert "boom" in body["error"]


@pytest.mark.asyncio
async def test_celery_task_503_when_celery_missing() -> None:
    app = FastAPI()
    app.include_router(tasks_router, prefix="/api/v1")
    app.state.celery_app = None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/tasks/celery/x")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_celery_task_503_on_backend_error(
    celery_app_obj: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(task_id: str, app: Any = None) -> Any:
        raise ConnectionError("redis down")

    monkeypatch.setattr(tasks_module, "AsyncResult", _boom)
    async with AsyncClient(
        transport=ASGITransport(app=celery_app_obj), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/tasks/celery/x")
    assert resp.status_code == 503
    assert "result backend unavailable" in resp.json()["error"]["message"]
