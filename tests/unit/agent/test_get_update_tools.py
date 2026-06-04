"""Single-read (get_*) and real-patch (update_*) management tools.

The patch tools must be *distinct* from the create-upsert tools — they target an
existing row by id/name and partially update it, returning ``not_found`` when the
row is absent (a create-upsert would silently resurrect it instead). These tests
pin that distinction by asserting the patch path is taken and the create path is
never touched.
"""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator, Callable
from unittest.mock import AsyncMock

import pytest

from intellisource.agent.tools.executes.manage import (
    _get_pipeline_execute,
    _get_source_execute,
    _get_subscription_execute,
    _update_pipeline_execute,
    _update_source_execute,
    _update_subscription_execute,
)
from intellisource.agent.tools.registry import AgentToolRegistry

SOURCE_UUID = "11111111-1111-1111-1111-111111111111"
SUB_UUID = "22222222-2222-2222-2222-222222222222"


def _deps(factory_attr: str, service: Any) -> SimpleNamespace:
    """ToolDeps-like object with one service factory + a session factory."""
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def _cm() -> AsyncIterator[Any]:
        yield session

    deps = SimpleNamespace(session_factory=lambda: _cm())
    setattr(deps, factory_attr, lambda _session: service)
    return deps


# ---------------------------------------------------------------------------
# get_source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_source_ok() -> None:
    row = SimpleNamespace(
        id=SOURCE_UUID,
        name="hn",
        type="rss",
        url="https://news.ycombinator.com/rss",
        status="active",
        tags=["tech"],
        discipline_tags=[],
        schedule_interval=3600,
    )
    svc = SimpleNamespace(get=AsyncMock(return_value=row))
    deps = _deps("source_service_factory", svc)
    result = await _get_source_execute(tool_deps=deps, source_id=SOURCE_UUID)
    assert result["status"] == "ok"
    assert result["source"]["name"] == "hn"
    assert result["source"]["url"] == "https://news.ycombinator.com/rss"
    assert result["source"]["tags"] == ["tech"]
    svc.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_source_not_found() -> None:
    svc = SimpleNamespace(get=AsyncMock(return_value=None))
    deps = _deps("source_service_factory", svc)
    result = await _get_source_execute(tool_deps=deps, source_id=SOURCE_UUID)
    assert result["status"] == "error"
    assert result["code"] == "not_found"


@pytest.mark.asyncio
async def test_get_source_invalid_uuid() -> None:
    svc = SimpleNamespace(get=AsyncMock())
    deps = _deps("source_service_factory", svc)
    result = await _get_source_execute(tool_deps=deps, source_id="not-a-uuid")
    assert result["code"] == "invalid_input"
    svc.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_source_not_wired() -> None:
    result = await _get_source_execute(tool_deps=None, source_id=SOURCE_UUID)
    assert result["code"] == "not_wired"


# ---------------------------------------------------------------------------
# get_subscription
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_subscription_ok() -> None:
    row = SimpleNamespace(
        id=SUB_UUID,
        name="daily",
        channel="email",
        status="active",
        frequency="daily",
        match_rules={"tags": ["tech"]},
    )
    svc = SimpleNamespace(get=AsyncMock(return_value=row))
    deps = _deps("subscription_service_factory", svc)
    result = await _get_subscription_execute(tool_deps=deps, subscription_id=SUB_UUID)
    assert result["status"] == "ok"
    assert result["subscription"]["channel"] == "email"
    assert result["subscription"]["match_rules"] == {"tags": ["tech"]}


@pytest.mark.asyncio
async def test_get_subscription_not_found() -> None:
    svc = SimpleNamespace(get=AsyncMock(return_value=None))
    deps = _deps("subscription_service_factory", svc)
    result = await _get_subscription_execute(tool_deps=deps, subscription_id=SUB_UUID)
    assert result["code"] == "not_found"


# ---------------------------------------------------------------------------
# update_source — real patch, NOT create-upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_source_ok_calls_patch_not_create() -> None:
    updated = SimpleNamespace(
        id=SOURCE_UUID,
        name="hn",
        type="rss",
        url="https://news.ycombinator.com/rss",
        status="paused",
        tags=[],
        discipline_tags=[],
        schedule_interval=7200,
    )
    svc = SimpleNamespace(
        patch=AsyncMock(return_value=updated),
        create=AsyncMock(),
    )
    deps = _deps("source_service_factory", svc)
    result = await _update_source_execute(
        tool_deps=deps, source_id=SOURCE_UUID, status="paused", schedule_interval=7200
    )
    assert result["status"] == "ok"
    assert result["source"]["status"] == "paused"
    assert result["source"]["schedule_interval"] == 7200
    # The defining property of update_* vs create_*: patch is called, create is not.
    svc.patch.assert_awaited_once()
    svc.create.assert_not_awaited()
    # Only the supplied fields are forwarded as the patch body (partial update).
    _id_arg, fields_arg = svc.patch.await_args.args
    assert fields_arg == {"status": "paused", "schedule_interval": 7200}


@pytest.mark.asyncio
async def test_update_source_not_found() -> None:
    svc = SimpleNamespace(patch=AsyncMock(return_value=None))
    deps = _deps("source_service_factory", svc)
    result = await _update_source_execute(
        tool_deps=deps, source_id=SOURCE_UUID, status="paused"
    )
    assert result["code"] == "not_found"


@pytest.mark.asyncio
async def test_update_source_no_fields_is_invalid() -> None:
    svc = SimpleNamespace(patch=AsyncMock())
    deps = _deps("source_service_factory", svc)
    result = await _update_source_execute(tool_deps=deps, source_id=SOURCE_UUID)
    assert result["code"] == "invalid_input"
    svc.patch.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_source_invalid_uuid() -> None:
    svc = SimpleNamespace(patch=AsyncMock())
    deps = _deps("source_service_factory", svc)
    result = await _update_source_execute(
        tool_deps=deps, source_id="nope", status="paused"
    )
    assert result["code"] == "invalid_input"
    svc.patch.assert_not_awaited()


# ---------------------------------------------------------------------------
# update_subscription — real patch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_subscription_ok_calls_patch_not_create() -> None:
    updated = SimpleNamespace(
        id=SUB_UUID,
        name="daily",
        channel="email",
        status="active",
        frequency="weekly",
        match_rules={},
    )
    svc = SimpleNamespace(patch=AsyncMock(return_value=updated), create=AsyncMock())
    deps = _deps("subscription_service_factory", svc)
    result = await _update_subscription_execute(
        tool_deps=deps, subscription_id=SUB_UUID, frequency="weekly"
    )
    assert result["status"] == "ok"
    assert result["subscription"]["frequency"] == "weekly"
    svc.patch.assert_awaited_once()
    svc.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_subscription_not_found() -> None:
    svc = SimpleNamespace(patch=AsyncMock(return_value=None))
    deps = _deps("subscription_service_factory", svc)
    result = await _update_subscription_execute(
        tool_deps=deps, subscription_id=SUB_UUID, frequency="weekly"
    )
    assert result["code"] == "not_found"


# ---------------------------------------------------------------------------
# update_pipeline — real patch (by name), NOT create-upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_pipeline_ok_calls_update_not_create() -> None:
    updated = SimpleNamespace(name="admin-agent", mode="flexible", max_steps=80)
    svc = SimpleNamespace(update=AsyncMock(return_value=updated), create=AsyncMock())
    deps = _deps("pipeline_service_factory", svc)
    result = await _update_pipeline_execute(
        tool_deps=deps, name="admin-agent", max_steps=80
    )
    assert result["status"] == "ok"
    assert result["pipeline"]["max_steps"] == 80
    svc.update.assert_awaited_once()
    svc.create.assert_not_awaited()
    name_arg, fields_arg = svc.update.await_args.args
    assert name_arg == "admin-agent"
    assert fields_arg == {"max_steps": 80}


@pytest.mark.asyncio
async def test_update_pipeline_not_found() -> None:
    svc = SimpleNamespace(update=AsyncMock(return_value=None))
    deps = _deps("pipeline_service_factory", svc)
    result = await _update_pipeline_execute(tool_deps=deps, name="ghost", max_steps=5)
    assert result["code"] == "not_found"


@pytest.mark.asyncio
async def test_update_pipeline_no_name_is_invalid() -> None:
    svc = SimpleNamespace(update=AsyncMock())
    deps = _deps("pipeline_service_factory", svc)
    result = await _update_pipeline_execute(tool_deps=deps, name="", max_steps=5)
    assert result["code"] == "invalid_input"
    svc.update.assert_not_awaited()


# ---------------------------------------------------------------------------
# Registry registration + schema contract
# ---------------------------------------------------------------------------


def test_management_tools_include_get_and_update() -> None:
    reg = AgentToolRegistry()
    reg.register_management_tools()
    tools = set(reg.list_tools())
    expected = {
        "get_source",
        "get_subscription",
        "update_source",
        "update_subscription",
        "update_pipeline",
    }
    assert expected.issubset(tools)

    # get_* tools are read-only; update_* tools mutate external state.
    for ro in ("get_source", "get_subscription"):
        defn = reg.get(ro)
        assert defn is not None and defn.mutates_external_state is False
    for rw in ("update_source", "update_subscription", "update_pipeline"):
        defn = reg.get(rw)
        assert defn is not None and defn.mutates_external_state is True


def _accepted_params(fn: Callable[..., Any]) -> set[str]:
    return {
        p.name
        for p in inspect.signature(fn).parameters.values()
        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        and p.name not in {"tool_deps", "kwargs"}
    }


def test_get_update_schemas_match_executor_signatures() -> None:
    """Every advertised id/name property must be a real executor parameter."""
    reg = AgentToolRegistry()
    reg.register_management_tools()
    pairs = [
        ("get_source", _get_source_execute, "source_id"),
        ("get_subscription", _get_subscription_execute, "subscription_id"),
        ("update_source", _update_source_execute, "source_id"),
        ("update_subscription", _update_subscription_execute, "subscription_id"),
        ("update_pipeline", _update_pipeline_execute, "name"),
    ]
    for tool_name, fn, key in pairs:
        defn = reg.get(tool_name)
        assert defn is not None
        props = set(defn.parameters.get("properties", {}))
        accepted = _accepted_params(fn)
        # The identifier property must be both advertised and accepted.
        assert key in props, f"{tool_name} must advertise {key}"
        assert key in accepted, f"{tool_name} executor must accept {key}"
        # No advertised scalar identifier may be unknown to the executor.
        assert key in props & accepted


# ---------------------------------------------------------------------------
# get_pipeline (parity with get_source / get_subscription / get_template)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pipeline_returns_full_config() -> None:
    cfg = SimpleNamespace(
        name="daily",
        mode="flexible",
        max_steps=25,
        on_failure="abort",
        steps=[],
        tools_allowed=["search"],
        tools_denied=[],
        system_prompt="hi",
        max_tokens_budget=16000,
        agent_mode="process",
        tool_permissions={"distribute": "confirm"},
    )
    service = SimpleNamespace(get=AsyncMock(return_value=cfg))
    deps = _deps("pipeline_service_factory", service)

    result = await _get_pipeline_execute(tool_deps=deps, name="daily")

    assert result["status"] == "ok"
    pipeline = result["pipeline"]
    # the full editable shape is returned so the LLM can get-then-update safely
    assert pipeline["name"] == "daily"
    assert pipeline["steps"] == []
    assert pipeline["system_prompt"] == "hi"
    assert pipeline["tool_permissions"] == {"distribute": "confirm"}
    service.get.assert_awaited_once_with("daily")


@pytest.mark.asyncio
async def test_get_pipeline_not_found() -> None:
    service = SimpleNamespace(get=AsyncMock(return_value=None))
    deps = _deps("pipeline_service_factory", service)

    result = await _get_pipeline_execute(tool_deps=deps, name="ghost")

    assert result["status"] == "error"
    assert result["code"] == "not_found"


@pytest.mark.asyncio
async def test_get_pipeline_requires_name() -> None:
    service = SimpleNamespace(get=AsyncMock())
    deps = _deps("pipeline_service_factory", service)

    result = await _get_pipeline_execute(tool_deps=deps, name="")

    assert result["code"] == "invalid_input"
    service.get.assert_not_awaited()


def test_get_pipeline_registered_and_granted_to_admin_agent() -> None:
    from pathlib import Path

    from intellisource.config.pipeline_models import PipelineConfig

    reg = AgentToolRegistry()
    reg.register_management_tools()
    defn = reg.get("get_pipeline")
    assert defn is not None
    assert defn.mutates_external_state is False  # read-only
    assert defn.parameters["required"] == ["name"]

    path = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "pipelines"
        / "admin-agent.yaml"
    )
    cfg = PipelineConfig.from_yaml(str(path))
    assert "get_pipeline" in cfg.tools_allowed
