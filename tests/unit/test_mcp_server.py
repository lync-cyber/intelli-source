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
        "list_templates",
        "get_template",
        "create_template",
        "delete_template",
    }
    assert expected.issubset(names)


def test_registers_p2_parity_tools() -> None:
    """P2: MCP transport reaches surface-parity with REST / agent tools."""
    mcp = build_mcp_server()
    names = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "get_source",
        "update_source",
        "delete_source",
        "get_subscription",
        "create_subscription",
        "update_subscription",
        "delete_subscription",
        "update_pipeline",
        "search",
        "get_content_detail",
        "get_task_status",
    }
    assert expected.issubset(names)


def test_tool_descriptions_are_three_part() -> None:
    """Each tool self-describes 职责 / 入参 / 返回 / 约束 so an LLM picks correctly."""
    mcp = build_mcp_server()
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    for name in ("create_source", "update_pipeline", "search", "delete_subscription"):
        desc = tools[name].description or ""
        # A three-part description is materially longer than a one-liner and
        # names what it returns and the precondition to call it.
        assert len(desc) > 80, f"{name} description too thin: {desc!r}"
        assert "Returns" in desc, f"{name} description must state its return shape"


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


@pytest.mark.asyncio
async def test_create_then_get_and_delete_template(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    created = _parse(
        await mcp.call_tool(
            "create_template",
            {
                "name": "mcp-brief",
                "base_template": "daily-brief",
                "formats": ["markdown"],
                "default_format": "markdown",
                "jinja_source": {"markdown": "# {{ bundle.title }}"},
            },
        )
    )
    assert created["name"] == "mcp-brief"
    assert created["base_template"] == "daily-brief"

    got = _parse(await mcp.call_tool("get_template", {"name": "mcp-brief"}))
    assert got["jinja_source"]["markdown"] == "# {{ bundle.title }}"

    listed = _parse(await mcp.call_tool("list_templates", {}))
    assert "mcp-brief" in {t["name"] for t in listed}

    deleted = _parse(await mcp.call_tool("delete_template", {"name": "mcp-brief"}))
    assert deleted["deleted"] is True
    gone = _parse(await mcp.call_tool("get_template", {"name": "mcp-brief"}))
    assert gone["error"] == "not_found"


@pytest.mark.asyncio
async def test_update_template_patches_existing(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    _parse(
        await mcp.call_tool(
            "create_template",
            {
                "name": "patch-me",
                "base_template": "daily-brief",
                "formats": ["markdown"],
                "default_format": "markdown",
                "jinja_source": {"markdown": "# x"},
            },
        )
    )
    updated = _parse(
        await mcp.call_tool(
            "update_template", {"name": "patch-me", "status": "archived"}
        )
    )
    assert updated["status"] == "archived"

    got = _parse(await mcp.call_tool("get_template", {"name": "patch-me"}))
    assert got["status"] == "archived"


@pytest.mark.asyncio
async def test_update_template_not_found(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(
        await mcp.call_tool("update_template", {"name": "ghost", "status": "archived"})
    )
    assert payload["error"] == "not_found"


@pytest.mark.asyncio
async def test_create_template_unknown_base_returns_error(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(
        await mcp.call_tool(
            "create_template",
            {
                "name": "bad-tpl",
                "base_template": "ghost",
                "formats": ["markdown"],
                "default_format": "markdown",
                "jinja_source": {"markdown": "x"},
            },
        )
    )
    assert payload["error"] == "invalid_input"


# ---------------------------------------------------------------------------
# P2: source get / update / delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_create_get_update_delete_cycle(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    created = _parse(
        await mcp.call_tool(
            "create_source",
            {"name": "hn", "type": "rss", "url": "https://news.ycombinator.com/rss"},
        )
    )
    sid = created["id"]

    got = _parse(await mcp.call_tool("get_source", {"source_id": sid}))
    assert got["name"] == "hn"
    assert got["url"] == "https://news.ycombinator.com/rss"

    updated = _parse(
        await mcp.call_tool("update_source", {"source_id": sid, "status": "paused"})
    )
    assert updated["status"] == "paused"

    deleted = _parse(await mcp.call_tool("delete_source", {"source_id": sid}))
    assert deleted["deleted"] is True


@pytest.mark.asyncio
async def test_get_source_not_found(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(
        await mcp.call_tool(
            "get_source", {"source_id": "33333333-3333-3333-3333-333333333333"}
        )
    )
    assert payload["error"] == "not_found"


@pytest.mark.asyncio
async def test_update_source_invalid_uuid(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(
        await mcp.call_tool("update_source", {"source_id": "nope", "status": "paused"})
    )
    assert payload["error"] == "invalid_input"


# ---------------------------------------------------------------------------
# P2: subscription create / get / update / delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_full_cycle(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    created = _parse(
        await mcp.call_tool(
            "create_subscription",
            {
                "name": "daily",
                "channel": "email",
                "channel_config": {"to_addr": "u@example.com"},
            },
        )
    )
    assert created["channel"] == "email"
    sid = created["id"]

    got = _parse(await mcp.call_tool("get_subscription", {"subscription_id": sid}))
    assert got["name"] == "daily"

    updated = _parse(
        await mcp.call_tool(
            "update_subscription", {"subscription_id": sid, "frequency": "weekly"}
        )
    )
    assert updated["frequency"] == "weekly"

    deleted = _parse(
        await mcp.call_tool("delete_subscription", {"subscription_id": sid})
    )
    assert deleted["deleted"] is True


@pytest.mark.asyncio
async def test_create_subscription_invalid_input(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(
        await mcp.call_tool(
            "create_subscription", {"name": "bad", "channel": "carrier-pigeon"}
        )
    )
    assert payload["error"] == "invalid_input"


# ---------------------------------------------------------------------------
# P2: pipeline update (patch, distinct from create)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_pipeline_patches_existing(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    updated = _parse(
        await mcp.call_tool("update_pipeline", {"name": "seeded", "max_steps": 99})
    )
    assert updated["name"] == "seeded"
    assert updated["max_steps"] == 99


@pytest.mark.asyncio
async def test_update_pipeline_not_found(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(
        await mcp.call_tool("update_pipeline", {"name": "ghost", "max_steps": 5})
    )
    assert payload["error"] == "not_found"


# ---------------------------------------------------------------------------
# P2: search / get_content_detail / get_task_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_delegates_to_engine(session_factory: Any) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from intellisource.search.hybrid import SearchResponse

    engine = MagicMock()
    engine.search = AsyncMock(
        return_value=SearchResponse(items=[], total=0, query_time_ms=4)
    )
    mcp = build_mcp_server(
        session_factory=session_factory,
        search_engine_factory=lambda _session: engine,
    )
    payload = _parse(await mcp.call_tool("search", {"query": "vector db", "top_k": 5}))
    assert payload["total"] == 0
    assert payload["items"] == []
    engine.search.assert_awaited_once()
    assert engine.search.await_args.kwargs["query"] == "vector db"
    assert engine.search.await_args.kwargs["limit"] == 5


@pytest.mark.asyncio
async def test_search_empty_query_is_invalid(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(await mcp.call_tool("search", {"query": ""}))
    assert payload["error"] == "invalid_input"


@pytest.mark.asyncio
async def test_get_content_detail_not_found(session_factory: Any) -> None:
    mcp = build_mcp_server(session_factory=session_factory)
    payload = _parse(
        await mcp.call_tool(
            "get_content_detail",
            {"content_id": "44444444-4444-4444-4444-444444444444"},
        )
    )
    assert payload["error"] == "not_found"


@pytest.mark.asyncio
async def test_get_task_status_ok_and_not_found(session_factory: Any) -> None:
    from intellisource.storage.models import TaskChain

    async with session_factory() as session:
        chain = TaskChain(
            pipeline_name="seeded",
            status="running",
            trigger_type="manual",
            execution_mode="flexible",
            total_steps=3,
            completed_steps=1,
        )
        session.add(chain)
        await session.commit()
        chain_id = str(chain.id)

    mcp = build_mcp_server(session_factory=session_factory)
    ok = _parse(await mcp.call_tool("get_task_status", {"task_chain_id": chain_id}))
    assert ok["status"] == "running"
    assert ok["completed_steps"] == 1
    assert ok["total_steps"] == 3

    missing = _parse(
        await mcp.call_tool(
            "get_task_status",
            {"task_chain_id": "55555555-5555-5555-5555-555555555555"},
        )
    )
    assert missing["error"] == "not_found"


def test_console_script_registered() -> None:
    """pyproject must expose ``intellisource-mcp`` so the server runs as a CLI."""
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts.get("intellisource-mcp") == "intellisource.mcp_server:main"


# ---------------------------------------------------------------------------
# T-MCP-GW: default gateway injection
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_gateway_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the MCP default-gateway singleton for the test; auto-restored after."""
    import intellisource.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "_llm_gateway_singleton", None)


def test_default_search_engine_has_llm_gateway(reset_gateway_singleton: None) -> None:
    """AC-1: HybridSearchEngine produced by the default factory carries a LLMGateway."""
    from unittest.mock import MagicMock

    import intellisource.mcp_server as mcp_mod
    from intellisource.llm.gateway import LLMGateway

    engine = mcp_mod._default_search_engine_factory(MagicMock())
    assert isinstance(engine._llm_gateway, LLMGateway)


def test_default_gateway_is_singleton(reset_gateway_singleton: None) -> None:
    """AC-2: calling _default_search_engine_factory twice shares one gateway."""
    from unittest.mock import MagicMock

    import intellisource.mcp_server as mcp_mod
    from intellisource.llm.gateway import LLMGateway

    engine_a = mcp_mod._default_search_engine_factory(MagicMock())
    engine_b = mcp_mod._default_search_engine_factory(MagicMock())
    # Both must be real LLMGateway and the exact same object.
    assert isinstance(engine_a._llm_gateway, LLMGateway)
    assert engine_a._llm_gateway is engine_b._llm_gateway


@pytest.mark.asyncio
async def test_explicit_search_factory_overrides_default(
    session_factory: Any, reset_gateway_singleton: None
) -> None:
    """AC-3: build_mcp_server honours an explicit search_engine_factory over default."""
    from unittest.mock import AsyncMock, MagicMock

    from intellisource.search.hybrid import SearchResponse

    custom_engine = MagicMock()
    custom_engine.search = AsyncMock(
        return_value=SearchResponse(items=[], total=0, query_time_ms=1)
    )
    mcp = build_mcp_server(
        session_factory=session_factory,
        search_engine_factory=lambda _session: custom_engine,
    )
    payload = _parse(await mcp.call_tool("search", {"query": "test-ac3"}))
    assert payload["total"] == 0
    custom_engine.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_default_engine_embed_triggers_semantic_branch(
    reset_gateway_singleton: None,
) -> None:
    """AC-4: with a stubbed gateway.embed the semantic branch is reached."""
    from unittest.mock import AsyncMock, MagicMock, patch

    import intellisource.mcp_server as mcp_mod

    engine = mcp_mod._default_search_engine_factory(MagicMock())

    fake_vector = [0.1] * 8
    engine._llm_gateway.embed = AsyncMock(return_value=fake_vector)

    with patch(
        "intellisource.storage.vector.HybridIndex.search", new_callable=AsyncMock
    ) as mock_index_search:
        mock_index_search.return_value = []
        await engine.search(query="semantic test", mode="hybrid")

    engine._llm_gateway.embed.assert_awaited_once_with("semantic test")
