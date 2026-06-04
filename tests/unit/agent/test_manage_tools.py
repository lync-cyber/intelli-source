"""Inc5 P2-1/P2-3: management CRUD tools + shared result helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest

from intellisource.agent.tools.executes.manage import (
    _create_pipeline_execute,
    _create_source_execute,
    _create_subscription_execute,
    _delete_pipeline_execute,
    _delete_source_execute,
    _list_pipelines_execute,
    _list_sources_execute,
)
from intellisource.agent.tools.registry import AgentToolRegistry
from intellisource.agent.tools.results import tool_error, tool_ok

SOURCE_UUID = "11111111-1111-1111-1111-111111111111"


def _deps(factory_attr: str, service: Any) -> SimpleNamespace:
    """Build a ToolDeps-like object with one service factory + a session factory."""
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def _cm() -> AsyncIterator[Any]:
        yield session

    deps = SimpleNamespace(session_factory=lambda: _cm())
    setattr(deps, factory_attr, lambda _session: service)
    return deps


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------


def test_tool_ok_and_error_shape() -> None:
    assert tool_ok("t", a=1) == {"status": "ok", "tool": "t", "a": 1}
    err = tool_error("t", "boom", code="not_found", x=2)
    assert err == {
        "status": "error",
        "tool": "t",
        "code": "not_found",
        "reason": "boom",
        "x": 2,
    }


# ---------------------------------------------------------------------------
# create_source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_source_ok() -> None:
    svc = SimpleNamespace(
        create=AsyncMock(
            return_value=SimpleNamespace(
                id=SOURCE_UUID, name="hn", type="rss", status="active"
            )
        )
    )
    deps = _deps("source_service_factory", svc)
    result = await _create_source_execute(
        tool_deps=deps, name="hn", type="rss", url="https://news.ycombinator.com/rss"
    )
    assert result["status"] == "ok"
    assert result["source"]["name"] == "hn"
    assert result["source"]["type"] == "rss"
    svc.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_source_invalid_input() -> None:
    svc = SimpleNamespace(create=AsyncMock())
    deps = _deps("source_service_factory", svc)
    # url without a scheme fails SourceConfig validation
    result = await _create_source_execute(
        tool_deps=deps, name="bad", type="rss", url="not-a-url"
    )
    assert result["status"] == "error"
    assert result["code"] == "invalid_input"
    svc.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_source_not_wired() -> None:
    result = await _create_source_execute(tool_deps=None, name="x")
    assert result["status"] == "error"
    assert result["code"] == "not_wired"


# ---------------------------------------------------------------------------
# list / delete sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_ok() -> None:
    rows = [
        SimpleNamespace(
            id=SOURCE_UUID, name="hn", type="rss", url="https://x", status="active"
        )
    ]
    svc = SimpleNamespace(
        list_paginated=AsyncMock(
            return_value={"items": rows, "next_cursor": None, "has_more": False}
        )
    )
    deps = _deps("source_service_factory", svc)
    result = await _list_sources_execute(tool_deps=deps, limit=10)
    assert result["status"] == "ok"
    assert result["count"] == 1
    assert result["items"][0]["name"] == "hn"


@pytest.mark.asyncio
async def test_delete_source_not_found() -> None:
    svc = SimpleNamespace(delete=AsyncMock(return_value=False))
    deps = _deps("source_service_factory", svc)
    result = await _delete_source_execute(tool_deps=deps, source_id=SOURCE_UUID)
    assert result["status"] == "error"
    assert result["code"] == "not_found"


@pytest.mark.asyncio
async def test_delete_source_invalid_uuid() -> None:
    svc = SimpleNamespace(delete=AsyncMock())
    deps = _deps("source_service_factory", svc)
    result = await _delete_source_execute(tool_deps=deps, source_id="nope")
    assert result["code"] == "invalid_input"
    svc.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# subscriptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_subscription_ok() -> None:
    svc = SimpleNamespace(
        create=AsyncMock(
            return_value=SimpleNamespace(
                id="22222222-2222-2222-2222-222222222222",
                name="daily",
                channel="email",
                status="active",
            )
        )
    )
    deps = _deps("subscription_service_factory", svc)
    result = await _create_subscription_execute(
        tool_deps=deps, name="daily", channel="email"
    )
    assert result["status"] == "ok"
    assert result["subscription"]["channel"] == "email"


# ---------------------------------------------------------------------------
# pipelines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_pipeline_ok() -> None:
    svc = SimpleNamespace(
        create=AsyncMock(
            return_value=SimpleNamespace(name="p", mode="flexible", max_steps=5)
        )
    )
    deps = _deps("pipeline_service_factory", svc)
    result = await _create_pipeline_execute(
        tool_deps=deps, name="p", mode="flexible", steps=[]
    )
    assert result["status"] == "ok"
    assert result["pipeline"]["name"] == "p"


@pytest.mark.asyncio
async def test_create_pipeline_invalid_mode() -> None:
    svc = SimpleNamespace(create=AsyncMock())
    deps = _deps("pipeline_service_factory", svc)
    result = await _create_pipeline_execute(tool_deps=deps, name="p", mode="bogus")
    assert result["code"] == "invalid_input"
    svc.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_pipeline_not_found() -> None:
    svc = SimpleNamespace(delete=AsyncMock(return_value=False))
    deps = _deps("pipeline_service_factory", svc)
    result = await _delete_pipeline_execute(tool_deps=deps, name="ghost")
    assert result["code"] == "not_found"


@pytest.mark.asyncio
async def test_list_pipelines_ok() -> None:
    svc = SimpleNamespace(
        list_summaries=AsyncMock(
            return_value=[{"name": "p", "mode": "flexible", "max_steps": 5}]
        )
    )
    deps = _deps("pipeline_service_factory", svc)
    result = await _list_pipelines_execute(tool_deps=deps)
    assert result["status"] == "ok"
    assert result["items"][0]["name"] == "p"


# ---------------------------------------------------------------------------
# Registry registration
# ---------------------------------------------------------------------------


def test_register_management_tools_adds_crud_tools() -> None:
    reg = AgentToolRegistry()
    reg.register_management_tools()
    tools = set(reg.list_tools())
    expected = {
        "create_source",
        "list_sources",
        "delete_source",
        "create_subscription",
        "list_subscriptions",
        "delete_subscription",
        "create_pipeline",
        "list_pipelines",
        "delete_pipeline",
    }
    assert expected.issubset(tools)

    create = reg.get("create_source")
    listing = reg.get("list_sources")
    assert create is not None and create.mutates_external_state is True
    assert listing is not None and listing.mutates_external_state is False


def test_admin_agent_yaml_is_valid_and_grants_management_tools() -> None:
    from pathlib import Path

    from intellisource.config.pipeline_models import PipelineConfig

    path = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "pipelines"
        / "admin-agent.yaml"
    )
    cfg = PipelineConfig.from_yaml(str(path))
    assert cfg.name == "admin-agent"
    assert cfg.mode == "flexible"
    for tool in ("create_source", "create_pipeline", "create_subscription"):
        assert tool in cfg.tools_allowed


def test_admin_agent_prompt_requires_distribute_confirmation() -> None:
    """P3 confirm-HITL: the prompt must demand explicit user sign-off before a
    real push, since distribute fans out to live subscribers."""
    from pathlib import Path

    from intellisource.config.pipeline_models import PipelineConfig

    path = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "pipelines"
        / "admin-agent.yaml"
    )
    cfg = PipelineConfig.from_yaml(str(path))
    prompt = cfg.system_prompt or ""
    assert "distribute" in prompt
    assert "确认" in prompt
