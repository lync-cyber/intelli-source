"""Gap close-out: agent get_template / update_template (full template CRUD parity).

The agent could already create/list/delete templates; these add single-read and
real-patch (by name) so the agent surface matches REST (which has GET + PATCH).
update_template must patch an existing row and return not_found when absent —
never silently create.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest

from intellisource.agent.tools.executes.manage import (
    _get_template_execute,
    _update_template_execute,
)
from intellisource.agent.tools.registry import AgentToolRegistry

TPL_UUID = "33333333-3333-3333-3333-333333333333"


def _deps(service: Any) -> SimpleNamespace:
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def _cm() -> AsyncIterator[Any]:
        yield session

    deps = SimpleNamespace(session_factory=lambda: _cm())
    deps.template_service_factory = lambda _s: service
    return deps


def _row(**over: Any) -> SimpleNamespace:
    base = {
        "id": TPL_UUID,
        "name": "brief",
        "base_template": "daily-brief",
        "formats": ["markdown"],
        "default_format": "markdown",
        "status": "active",
    }
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_get_template_ok() -> None:
    svc = SimpleNamespace(get_by_name=AsyncMock(return_value=_row()))
    result = await _get_template_execute(tool_deps=_deps(svc), name="brief")
    assert result["status"] == "ok"
    assert result["template"]["base_template"] == "daily-brief"
    assert result["template"]["formats"] == ["markdown"]


@pytest.mark.asyncio
async def test_get_template_not_found() -> None:
    svc = SimpleNamespace(get_by_name=AsyncMock(return_value=None))
    result = await _get_template_execute(tool_deps=_deps(svc), name="ghost")
    assert result["code"] == "not_found"


@pytest.mark.asyncio
async def test_update_template_patches_not_creates() -> None:
    svc = SimpleNamespace(
        get_by_name=AsyncMock(return_value=_row()),
        patch=AsyncMock(return_value=_row(status="archived")),
        create=AsyncMock(),
    )
    result = await _update_template_execute(
        tool_deps=_deps(svc), name="brief", status="archived"
    )
    assert result["status"] == "ok"
    assert result["template"]["status"] == "archived"
    svc.patch.assert_awaited_once()
    svc.create.assert_not_awaited()
    # patch targets the resolved row id with only the supplied fields
    id_arg, fields_arg = svc.patch.await_args.args
    assert id_arg == TPL_UUID
    assert fields_arg == {"status": "archived"}


@pytest.mark.asyncio
async def test_update_template_not_found() -> None:
    svc = SimpleNamespace(get_by_name=AsyncMock(return_value=None), patch=AsyncMock())
    result = await _update_template_execute(
        tool_deps=_deps(svc), name="ghost", status="archived"
    )
    assert result["code"] == "not_found"
    svc.patch.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_template_no_fields_invalid() -> None:
    svc = SimpleNamespace(get_by_name=AsyncMock(), patch=AsyncMock())
    result = await _update_template_execute(tool_deps=_deps(svc), name="brief")
    assert result["code"] == "invalid_input"
    svc.get_by_name.assert_not_awaited()


def test_template_tools_registered_full_crud() -> None:
    reg = AgentToolRegistry()
    reg.register_management_tools()
    tools = set(reg.list_tools())
    assert {
        "create_template",
        "list_templates",
        "get_template",
        "update_template",
        "delete_template",
    } <= tools

    get_defn = reg.get("get_template")
    upd_defn = reg.get("update_template")
    assert get_defn is not None and get_defn.mutates_external_state is False
    assert upd_defn is not None and upd_defn.mutates_external_state is True


def test_admin_agent_yaml_grants_template_get_update() -> None:
    from pathlib import Path

    from intellisource.config.pipeline_models import PipelineConfig

    path = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "pipelines"
        / "admin-agent.yaml"
    )
    cfg = PipelineConfig.from_yaml(str(path))
    assert "get_template" in cfg.tools_allowed
    assert "update_template" in cfg.tools_allowed
