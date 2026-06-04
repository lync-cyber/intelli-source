"""P1-b: templates CRUD router over a real (SQLite) service.

Mirrors the subscriptions/pipelines router test pattern: an in-memory SQLite
service is wired via a dependency override; the router is a thin shell over
TemplateService.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from intellisource.api.routers.templates import _get_service
from intellisource.api.routers.templates import router as templates_router
from intellisource.storage.models import Base
from intellisource.template.service import TemplateService

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _set_sqlite_fk_pragma(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
    db = factory()
    yield db
    await db.close()
    await eng.dispose()


def _make_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.include_router(templates_router, prefix="/api/v1")
    app.dependency_overrides[_get_service] = lambda: TemplateService(session)
    return app


def _valid_body(name: str = "my-brief", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "base_template": "daily-brief",
        "formats": ["markdown", "text"],
        "default_format": "markdown",
        "jinja_source": {
            "markdown": "# {{ bundle.title }}",
            "text": "{{ bundle.title }}",
        },
        "aggregate_config": {"title": "我的速览"},
    }
    body.update(overrides)
    return body


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_create_then_get_detail(session: AsyncSession) -> None:
    app = _make_app(session)
    async with await _client(app) as client:
        created = await client.post("/api/v1/templates", json=_valid_body())
        assert created.status_code == 201
        body = created.json()
        assert body["name"] == "my-brief"
        assert body["source"] == "db"
        assert body["base_template"] == "daily-brief"
        assert set(body["formats"]) == {"markdown", "text"}

        got = await client.get("/api/v1/templates/my-brief")
        assert got.status_code == 200
        assert got.json()["jinja_source"]["markdown"] == "# {{ bundle.title }}"


@pytest.mark.asyncio
async def test_create_unknown_base_template_returns_422(session: AsyncSession) -> None:
    app = _make_app(session)
    async with await _client(app) as client:
        resp = await client.post(
            "/api/v1/templates", json=_valid_body(base_template="ghost")
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_invalid_structure_returns_422(session: AsyncSession) -> None:
    app = _make_app(session)
    async with await _client(app) as client:
        # default_format not in formats → pydantic validation 422
        resp = await client.post(
            "/api/v1/templates",
            json=_valid_body(default_format="html"),
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_builtin_detail(session: AsyncSession) -> None:
    app = _make_app(session)
    async with await _client(app) as client:
        resp = await client.get("/api/v1/templates/daily-brief")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "builtin"
    assert body["default_format"] in body["formats"]


@pytest.mark.asyncio
async def test_get_unknown_returns_404(session: AsyncSession) -> None:
    app = _make_app(session)
    async with await _client(app) as client:
        resp = await client.get("/api/v1/templates/nope-not-here")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_updates_source(session: AsyncSession) -> None:
    app = _make_app(session)
    async with await _client(app) as client:
        await client.post("/api/v1/templates", json=_valid_body())
        resp = await client.patch(
            "/api/v1/templates/my-brief",
            json={"aggregate_config": {"title": "改后标题"}},
        )
        assert resp.status_code == 200
        assert resp.json()["aggregate_config"]["title"] == "改后标题"


@pytest.mark.asyncio
async def test_patch_unknown_returns_404(session: AsyncSession) -> None:
    app = _make_app(session)
    async with await _client(app) as client:
        resp = await client.patch(
            "/api/v1/templates/ghost", json={"status": "archived"}
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_then_absent(session: AsyncSession) -> None:
    app = _make_app(session)
    async with await _client(app) as client:
        await client.post("/api/v1/templates", json=_valid_body())
        deleted = await client.delete("/api/v1/templates/my-brief")
        assert deleted.status_code == 204
        again = await client.get("/api/v1/templates/my-brief")
        assert again.status_code == 404


@pytest.mark.asyncio
async def test_delete_unknown_returns_404(session: AsyncSession) -> None:
    app = _make_app(session)
    async with await _client(app) as client:
        resp = await client.delete("/api/v1/templates/ghost")
    assert resp.status_code == 404
