"""Unit tests for the Pipelines router (AC-T099-1/2/3/8).

The router is a thin shell over PipelineDefinitionService; tests wire a
SQLite-backed service (seeded from the shipped YAML configs) via a
dependency override, mirroring the sources-router test pattern.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from intellisource.api.routers.pipelines import _get_service
from intellisource.api.routers.pipelines import router as pipelines_router
from intellisource.pipeline.definition_service import PipelineDefinitionService
from intellisource.storage.models import Base

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _set_sqlite_fk_pragma(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@pytest_asyncio.fixture
async def seeded_session():
    """In-memory SQLite session seeded with the shipped pipeline YAML configs."""
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    await PipelineDefinitionService(session).seed_from_yaml()
    yield session
    await session.close()
    await eng.dispose()


def _make_app(seeded_session: AsyncSession, *, with_celery: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(pipelines_router, prefix="/api/v1")
    app.dependency_overrides[_get_service] = lambda: PipelineDefinitionService(
        seeded_session
    )
    if with_celery:
        celery_app = MagicMock()
        task_result = MagicMock()
        task_result.id = "task-fake-001"
        celery_app.send_task = MagicMock(return_value=task_result)
        app.state.celery_app = celery_app
    return app


class TestListPipelines:
    async def test_list_returns_known_pipelines(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/pipelines")

        assert resp.status_code == 200
        names = {item["name"] for item in resp.json()}
        for expected in {
            "instant-search",
            "content-process",
            "manual-collect",
            "push-optimize",
            "scheduled-collect",
        }:
            assert expected in names, f"expected '{expected}' in {names}"

    async def test_list_item_shape(self, seeded_session: AsyncSession) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/pipelines")

        items = resp.json()
        assert items, "expected at least one pipeline"
        for item in items:
            assert {"name", "mode", "max_steps", "tools_allowed"}.issubset(item.keys())


class TestGetPipeline:
    async def test_get_known_pipeline_returns_config(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/pipelines/instant-search")

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "instant-search"
        assert "mode" in body
        assert "steps" in body

    async def test_get_unknown_pipeline_returns_404(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/pipelines/does-not-exist")

        assert resp.status_code == 404


class TestRunPipeline:
    async def test_run_dispatches_celery_task_with_kwargs(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/pipelines/instant-search/run",
                json={"params": {"foo": "bar"}},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == "task-fake-001"
        # a correlatable TaskChain id is returned for GET /tasks/chains/{id}
        chain_id = body["task_chain_id"]
        assert uuid.UUID(chain_id)

        call = app.state.celery_app.send_task.call_args
        assert call.args[0] == "run_pipeline"
        kwargs = call.kwargs["kwargs"]
        assert kwargs["pipeline_name"] == "instant-search"
        # caller params preserved, plus the same task_chain_id handed to the worker
        assert kwargs["params"]["foo"] == "bar"
        assert kwargs["params"]["task_chain_id"] == chain_id

    async def test_run_unknown_pipeline_returns_404(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/pipelines/does-not-exist/run", json={"params": {}}
            )

        assert resp.status_code == 404

    async def test_run_returns_503_when_celery_unconfigured(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session, with_celery=False)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/pipelines/instant-search/run", json={"params": {}}
            )

        assert resp.status_code == 503


class TestPathTraversalGuard:
    """Unknown / traversal names resolve to 404 (DB lookup miss); no dispatch."""

    @pytest.mark.parametrize(
        "bad_name",
        [
            "..%2fsources%2fanything",
            ".hidden",
            "with space",
            "中文",
        ],
    )
    async def test_get_pipeline_rejects_bad_name(
        self, seeded_session: AsyncSession, bad_name: str
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/v1/pipelines/{bad_name}")

        assert resp.status_code == 404

    async def test_run_pipeline_rejects_path_traversal_name(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/pipelines/..%2fsources%2fevil/run", json={"params": {}}
            )

        assert resp.status_code == 404
        assert app.state.celery_app.send_task.call_args is None, (
            "Celery send_task must NOT have been dispatched for traversal name"
        )


class TestCreatePipeline:
    async def test_create_then_get_roundtrip(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/pipelines",
                json={
                    "name": "new-pipe",
                    "mode": "flexible",
                    "steps": [{"tool": "search", "params": {}}],
                    "tools_allowed": ["search"],
                },
            )
            assert resp.status_code == 201, resp.text
            assert resp.json()["name"] == "new-pipe"

            got = await client.get("/api/v1/pipelines/new-pipe")
            assert got.status_code == 200
            assert got.json()["tools_allowed"] == ["search"]

    async def test_create_invalid_mode_returns_422(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/pipelines",
                json={"name": "bad", "mode": "bogus", "steps": []},
            )
        assert resp.status_code == 422


class TestPatchPipeline:
    async def test_patch_updates_single_field(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.patch(
                "/api/v1/pipelines/instant-search", json={"max_steps": 99}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["max_steps"] == 99

            got = await client.get("/api/v1/pipelines/instant-search")
            assert got.json()["max_steps"] == 99

    async def test_patch_unknown_returns_404(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.patch(
                "/api/v1/pipelines/does-not-exist", json={"max_steps": 1}
            )
        assert resp.status_code == 404


class TestDeletePipeline:
    async def test_delete_then_gone(self, seeded_session: AsyncSession) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/v1/pipelines",
                json={"name": "doomed", "mode": "flexible", "steps": []},
            )
            resp = await client.delete("/api/v1/pipelines/doomed")
            assert resp.status_code == 204

            got = await client.get("/api/v1/pipelines/doomed")
            assert got.status_code == 404

    async def test_delete_absent_returns_404(
        self, seeded_session: AsyncSession
    ) -> None:
        app = _make_app(seeded_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/v1/pipelines/ghost")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_router_registered_in_main_app(
    main_openapi_paths: dict[str, Any],
) -> None:
    """AC-T099-3: main.create_app exposes /api/v1/pipelines in OpenAPI."""
    assert "/api/v1/pipelines" in main_openapi_paths, (
        f"/api/v1/pipelines not in OpenAPI; got: {sorted(main_openapi_paths.keys())}"
    )
