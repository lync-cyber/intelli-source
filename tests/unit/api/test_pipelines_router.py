"""Unit tests for the Pipelines router (AC-T099-1/2/3/8)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _make_pipelines_app(*, with_celery: bool = True) -> FastAPI:
    from intellisource.api.routers.pipelines import router as pipelines_router

    app = FastAPI()
    app.include_router(pipelines_router, prefix="/api/v1")
    if with_celery:
        celery_app = MagicMock()
        task_result = MagicMock()
        task_result.id = "task-fake-001"
        celery_app.send_task = MagicMock(return_value=task_result)
        app.state.celery_app = celery_app
    return app


class TestListPipelines:
    """AC-T099-1: GET /pipelines lists installed YAML configs."""

    async def test_list_returns_known_pipelines(self) -> None:
        """GET /pipelines returns at least the 5 shipped configs."""
        app = _make_pipelines_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/pipelines")

        assert resp.status_code == 200
        items: list[dict[str, Any]] = resp.json()
        names = {item["name"] for item in items}
        for expected in {
            "instant-search",
            "content-process",
            "manual-collect",
            "push-optimize",
            "scheduled-collect",
        }:
            assert expected in names, f"expected '{expected}' in {names}"

    async def test_list_item_shape(self) -> None:
        """Each list item exposes name + mode + max_steps + tools_allowed."""
        app = _make_pipelines_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/pipelines")

        items = resp.json()
        assert items, "expected at least one pipeline"
        for item in items:
            assert set(["name", "mode", "max_steps", "tools_allowed"]).issubset(
                item.keys()
            )


class TestGetPipeline:
    """AC-T099-1: GET /pipelines/{name} returns parsed PipelineConfig."""

    async def test_get_known_pipeline_returns_config(self) -> None:
        app = _make_pipelines_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/pipelines/instant-search")

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "instant-search"
        assert "mode" in body
        assert "steps" in body

    async def test_get_unknown_pipeline_returns_404(self) -> None:
        app = _make_pipelines_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/pipelines/does-not-exist")

        assert resp.status_code == 404


class TestRunPipeline:
    """AC-T099-2: POST /pipelines/{name}/run dispatches send_task."""

    async def test_run_dispatches_celery_task_with_kwargs(self) -> None:
        app = _make_pipelines_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/pipelines/instant-search/run",
                json={"params": {"foo": "bar"}},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body == {"task_id": "task-fake-001"}

        call = app.state.celery_app.send_task.call_args
        assert call.args[0] == "run_pipeline"
        kwargs = call.kwargs["kwargs"]
        assert kwargs["pipeline_name"] == "instant-search"
        assert kwargs["params"] == {"foo": "bar"}

    async def test_run_unknown_pipeline_returns_404(self) -> None:
        app = _make_pipelines_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/pipelines/does-not-exist/run",
                json={"params": {}},
            )

        assert resp.status_code == 404

    async def test_run_returns_503_when_celery_unconfigured(self) -> None:
        app = _make_pipelines_app(with_celery=False)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/pipelines/instant-search/run",
                json={"params": {}},
            )

        assert resp.status_code == 503


class TestPathTraversalGuard:
    """R-001: get_pipeline + run_pipeline reject path-traversal `name` inputs."""

    @pytest.mark.parametrize(
        "bad_name",
        [
            "../sources/something",
            "..%2fsources%2fanything",
            ".hidden",
            "with space",
            "with/slash",
            "中文",
        ],
    )
    async def test_get_pipeline_rejects_bad_name(self, bad_name: str) -> None:
        app = _make_pipelines_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/v1/pipelines/{bad_name}")

        assert resp.status_code == 404

    async def test_run_pipeline_rejects_path_traversal_name(self) -> None:
        app = _make_pipelines_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/pipelines/..%2fsources%2fevil/run",
                json={"params": {}},
            )

        assert resp.status_code == 404
        assert app.state.celery_app.send_task.call_args is None, (
            "Celery send_task must NOT have been dispatched for traversal name"
        )


@pytest.mark.asyncio
async def test_router_registered_in_main_app() -> None:
    """AC-T099-3: main.create_app exposes /api/v1/pipelines in OpenAPI."""
    from intellisource.main import create_app

    app = create_app()
    paths = app.openapi().get("paths", {})
    assert "/api/v1/pipelines" in paths, (
        f"/api/v1/pipelines not in OpenAPI; got: {sorted(paths.keys())}"
    )
