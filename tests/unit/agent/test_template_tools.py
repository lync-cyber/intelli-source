"""P1-b: template management agent tools (create/list/delete_template)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.agent.factory import build_agent_runner
from intellisource.agent.tools.executes.manage import (
    _create_template_execute,
    _delete_template_execute,
    _list_templates_execute,
)
from intellisource.agent.tools.registry import AgentToolRegistry
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.config.template_models import TemplateValidationError

TPL_UUID = "44444444-4444-4444-4444-444444444444"


def _deps(service: Any) -> SimpleNamespace:
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def _cm() -> AsyncIterator[Any]:
        yield session

    return SimpleNamespace(
        session_factory=lambda: _cm(),
        template_service_factory=lambda _s: service,
    )


@pytest.mark.asyncio
async def test_create_template_ok() -> None:
    svc = SimpleNamespace(
        create=AsyncMock(
            return_value=SimpleNamespace(
                id=TPL_UUID, name="t", base_template="daily-brief", status="active"
            )
        )
    )
    result = await _create_template_execute(
        tool_deps=_deps(svc),
        name="t",
        base_template="daily-brief",
        formats=["markdown"],
        default_format="markdown",
        jinja_source={"markdown": "x"},
    )
    assert result["status"] == "ok"
    assert result["template"]["name"] == "t"
    assert result["template"]["base_template"] == "daily-brief"
    svc.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_template_invalid_structure() -> None:
    svc = SimpleNamespace(create=AsyncMock())
    # default_format not in formats → TemplateConfig structural validation fails
    result = await _create_template_execute(
        tool_deps=_deps(svc),
        name="t",
        base_template="daily-brief",
        formats=["markdown"],
        default_format="html",
    )
    assert result["code"] == "invalid_input"
    svc.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_template_service_validation_error() -> None:
    svc = SimpleNamespace(
        create=AsyncMock(side_effect=TemplateValidationError("unknown base"))
    )
    result = await _create_template_execute(
        tool_deps=_deps(svc),
        name="t",
        base_template="ghost",
        formats=["markdown"],
        default_format="markdown",
        jinja_source={"markdown": "x"},
    )
    assert result["code"] == "invalid_input"
    assert "unknown base" in result["reason"]


@pytest.mark.asyncio
async def test_create_template_not_wired() -> None:
    result = await _create_template_execute(tool_deps=None, name="t")
    assert result["code"] == "not_wired"


@pytest.mark.asyncio
async def test_list_templates_ok() -> None:
    rows = [
        SimpleNamespace(
            id=TPL_UUID,
            name="t",
            base_template="daily-brief",
            default_format="markdown",
            status="active",
        )
    ]
    svc = SimpleNamespace(
        list_paginated=AsyncMock(
            return_value={"items": rows, "next_cursor": None, "has_more": False}
        )
    )
    result = await _list_templates_execute(tool_deps=_deps(svc), limit=10)
    assert result["status"] == "ok"
    assert result["count"] == 1
    assert result["items"][0]["name"] == "t"
    assert result["items"][0]["base_template"] == "daily-brief"


@pytest.mark.asyncio
async def test_delete_template_ok() -> None:
    svc = SimpleNamespace(
        get_by_name=AsyncMock(return_value=SimpleNamespace(id=TPL_UUID, name="t")),
        delete=AsyncMock(return_value=True),
    )
    result = await _delete_template_execute(tool_deps=_deps(svc), name="t")
    assert result["status"] == "ok"
    assert result["name"] == "t"
    svc.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_template_not_found() -> None:
    svc = SimpleNamespace(get_by_name=AsyncMock(return_value=None), delete=AsyncMock())
    result = await _delete_template_execute(tool_deps=_deps(svc), name="ghost")
    assert result["code"] == "not_found"
    svc.delete.assert_not_awaited()


def test_management_tools_include_template_crud() -> None:
    reg = AgentToolRegistry()
    reg.register_management_tools()
    tools = set(reg.list_tools())
    assert {"create_template", "list_templates", "delete_template"}.issubset(tools)

    create = reg.get("create_template")
    assert create is not None
    assert create.mutates_external_state is True
    listing = reg.get("list_templates")
    assert listing is not None
    assert listing.mutates_external_state is False


def test_admin_agent_grants_template_tools() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "pipelines"
        / "admin-agent.yaml"
    )
    cfg = PipelineConfig.from_yaml(str(path))
    for tool in ("create_template", "list_templates", "delete_template"):
        assert tool in cfg.tools_allowed


def test_build_agent_runner_binds_template_service_factory() -> None:
    factory = MagicMock()
    runner = build_agent_runner(
        session_factory=MagicMock(),
        llm_gateway=MagicMock(),
        collector_registry=MagicMock(),
        distributor=MagicMock(),
        search_engine_factory=MagicMock(),
        template_service_factory=factory,
    )
    assert runner._tool_deps is not None
    assert runner._tool_deps.template_service_factory is factory
