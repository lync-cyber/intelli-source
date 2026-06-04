"""Inc6 P3: MCP server — thin adapter over the domain services."""

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from intellisource.config.pipeline_models import PipelineConfig
from intellisource.mcp_server import build_mcp_server
from intellisource.pipeline.definition_service import PipelineDefinitionService
from intellisource.storage.models import Base


def _set_fk_pragma(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@pytest_asyncio.fixture
async def session_factory() -> Any:
    """Shared in-memory SQLite (StaticPool) seeded with one pipeline."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    event.listen(eng.sync_engine, "connect", _set_fk_pragma)
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await PipelineDefinitionService(session).create(
            PipelineConfig.from_dict(
                {"name": "seeded", "mode": "flexible", "steps": []}
            )
        )
        await session.commit()
    yield factory
    await eng.dispose()


def _parse(result: Any) -> Any:
    """Extract the JSON payload from a FastMCP call_tool result.

    call_tool returns ``(content_blocks, structured)``; list returns are wrapped
    under ``{"result": [...]}``. Prefer the structured content, falling back to
    the first content block's JSON text.
    """
    content = result[0] if isinstance(result, tuple) else result
    structured = result[1] if isinstance(result, tuple) else None
    if isinstance(structured, dict):
        if list(structured.keys()) == ["result"]:
            return structured["result"]
        return structured
    return json.loads(content[0].text)


def test_registers_expected_tools() -> None:
    mcp = build_mcp_server()
    names = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "list_pipelines",
        "get_pipeline",
        "create_pipeline",
        "delete_pipeline",
        "list_sources",
        "create_source",
        "list_subscriptions",
        "trigger_pipeline",
    }
    assert expected.issubset(names)


@pytest.mark.asyncio
async def test_list_pipelines_returns_seeded(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(await mcp.call_tool("list_pipelines", {}))
    names = {p["name"] for p in payload}
    assert "seeded" in names


@pytest.mark.asyncio
async def test_create_then_get_pipeline(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    created = _parse(
        await mcp.call_tool(
            "create_pipeline", {"name": "viamcp", "mode": "strict", "steps": []}
        )
    )
    assert created["name"] == "viamcp"
    assert created["mode"] == "strict"

    got = _parse(await mcp.call_tool("get_pipeline", {"name": "viamcp"}))
    assert got["name"] == "viamcp"


@pytest.mark.asyncio
async def test_get_unknown_pipeline_returns_error(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(await mcp.call_tool("get_pipeline", {"name": "nope"}))
    assert payload["error"] == "not_found"


@pytest.mark.asyncio
async def test_create_source_invalid_url(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(
        await mcp.call_tool(
            "create_source",
            {"name": "bad", "type": "rss", "url": "not-a-url"},
        )
    )
    assert payload["error"] == "invalid_input"
