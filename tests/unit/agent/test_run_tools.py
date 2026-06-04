"""run_pipeline + get_task_status agent tools.

The agent dispatches a persisted pipeline and polls its TaskChain status. Both
delegate to dependencies injected via ``ToolDeps`` (a Celery dispatcher callable
and a TaskChain repository factory), so they are unit-testable without a broker
or a database.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest

from intellisource.agent.tools.executes.run import (
    _get_task_status_execute,
    _run_pipeline_execute,
)
from intellisource.agent.tools.registry import AgentToolRegistry

CHAIN_UUID = "33333333-3333-3333-3333-333333333333"


def _deps(**extra: Any) -> SimpleNamespace:
    """ToolDeps-like object with a session_factory plus injected factories."""
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def _cm() -> AsyncIterator[Any]:
        yield session

    deps = SimpleNamespace(session_factory=lambda: _cm())
    for key, value in extra.items():
        setattr(deps, key, value)
    return deps


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_pipeline_dispatches_when_pipeline_exists() -> None:
    pipeline_svc = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(name="daily"))
    )
    dispatched: list[tuple[str, dict[str, Any]]] = []

    def _dispatcher(name: str, params: dict[str, Any]) -> Any:
        dispatched.append((name, params))
        return SimpleNamespace(id="celery-task-7")

    deps = _deps(
        pipeline_service_factory=lambda _s: pipeline_svc,
        task_dispatcher=_dispatcher,
    )
    result = await _run_pipeline_execute(tool_deps=deps, name="daily", params={"k": 1})

    assert result["status"] == "ok"
    assert result["celery_task_id"] == "celery-task-7"
    assert result["pipeline"] == "daily"
    # existence is verified before dispatch, and the dispatcher receives the
    # exact name + caller params (guards against a param being dropped en route)
    assert len(dispatched) == 1
    dispatched_name, dispatched_params = dispatched[0]
    assert dispatched_name == "daily"
    assert dispatched_params["k"] == 1
    pipeline_svc.get.assert_awaited_once_with("daily")


@pytest.mark.asyncio
async def test_run_pipeline_returns_task_chain_id_handed_to_worker() -> None:
    """The returned task_chain_id is exactly the one dispatched to the worker.

    This is the closed loop at the tool layer: a caller can feed run_pipeline's
    task_chain_id straight into get_task_status because the worker persists the
    run under that same id (see scheduler.tasks._ensure_chain).
    """
    pipeline_svc = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(name="daily"))
    )
    dispatched: list[tuple[str, dict[str, Any]]] = []

    def _dispatcher(name: str, params: dict[str, Any]) -> Any:
        dispatched.append((name, params))
        return SimpleNamespace(id="celery-task-9")

    deps = _deps(
        pipeline_service_factory=lambda _s: pipeline_svc,
        task_dispatcher=_dispatcher,
    )
    result = await _run_pipeline_execute(tool_deps=deps, name="daily")

    chain_id = result["task_chain_id"]
    # a valid UUID was generated and is distinct from the celery task id
    assert uuid.UUID(chain_id)
    assert chain_id != result["celery_task_id"]
    # and it is the id handed to the worker via params (not the lock key)
    assert dispatched[0][1]["task_chain_id"] == chain_id
    assert "task_id" not in dispatched[0][1]


@pytest.mark.asyncio
async def test_run_pipeline_unknown_name_never_dispatches() -> None:
    pipeline_svc = SimpleNamespace(get=AsyncMock(return_value=None))
    dispatch_calls = {"count": 0}

    def _dispatcher(name: str, params: dict[str, Any]) -> Any:
        dispatch_calls["count"] += 1
        return SimpleNamespace(id="should-not-happen")

    deps = _deps(
        pipeline_service_factory=lambda _s: pipeline_svc,
        task_dispatcher=_dispatcher,
    )
    result = await _run_pipeline_execute(tool_deps=deps, name="ghost")

    assert result["status"] == "error"
    assert result["code"] == "not_found"
    # an unknown / path-traversal name must not reach the broker
    assert dispatch_calls["count"] == 0


@pytest.mark.asyncio
async def test_run_pipeline_requires_name() -> None:
    deps = _deps(
        pipeline_service_factory=lambda _s: SimpleNamespace(get=AsyncMock()),
        task_dispatcher=lambda _n, _p: SimpleNamespace(id="x"),
    )
    result = await _run_pipeline_execute(tool_deps=deps, name="")

    assert result["status"] == "error"
    assert result["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_run_pipeline_not_wired() -> None:
    result = await _run_pipeline_execute(tool_deps=None, name="daily")

    assert result["status"] == "error"
    assert result["code"] == "not_wired"


@pytest.mark.asyncio
async def test_run_pipeline_dispatch_failure_is_reported() -> None:
    pipeline_svc = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(name="daily"))
    )

    def _boom(name: str, params: dict[str, Any]) -> Any:
        raise RuntimeError("broker down")

    deps = _deps(
        pipeline_service_factory=lambda _s: pipeline_svc,
        task_dispatcher=_boom,
    )
    result = await _run_pipeline_execute(tool_deps=deps, name="daily")

    assert result["status"] == "error"
    assert result["code"] == "dispatch_failed"
    assert "broker down" in result["reason"]


# ---------------------------------------------------------------------------
# get_task_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_status_returns_chain_fields() -> None:
    chain = SimpleNamespace(
        id=CHAIN_UUID,
        status="success",
        completed_steps=3,
        total_steps=3,
        error_message=None,
    )
    repo = SimpleNamespace(get=AsyncMock(return_value=chain))
    deps = _deps(task_chain_repo_factory=lambda _s: repo)

    result = await _get_task_status_execute(tool_deps=deps, task_chain_id=CHAIN_UUID)

    assert result["status"] == "ok"
    # chain state is nested under "task" so the run status never collides with
    # the tool-envelope "status" (ok/error) key
    assert result["task"]["status"] == "success"
    assert result["task"]["task_chain_id"] == CHAIN_UUID
    assert result["task"]["completed_steps"] == 3
    assert result["task"]["total_steps"] == 3
    repo.get.assert_awaited_once_with(CHAIN_UUID)


@pytest.mark.asyncio
async def test_get_task_status_not_found() -> None:
    repo = SimpleNamespace(get=AsyncMock(return_value=None))
    deps = _deps(task_chain_repo_factory=lambda _s: repo)

    result = await _get_task_status_execute(tool_deps=deps, task_chain_id=CHAIN_UUID)

    assert result["status"] == "error"
    assert result["code"] == "not_found"


@pytest.mark.asyncio
async def test_get_task_status_requires_id() -> None:
    repo = SimpleNamespace(get=AsyncMock())
    deps = _deps(task_chain_repo_factory=lambda _s: repo)

    result = await _get_task_status_execute(tool_deps=deps, task_chain_id="")

    assert result["code"] == "invalid_input"
    repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_task_status_not_wired() -> None:
    result = await _get_task_status_execute(tool_deps=None, task_chain_id=CHAIN_UUID)

    assert result["status"] == "error"
    assert result["code"] == "not_wired"


# ---------------------------------------------------------------------------
# registry registration + schema contracts
# ---------------------------------------------------------------------------


def test_management_tools_include_run_and_status() -> None:
    reg = AgentToolRegistry()
    reg.register_management_tools()
    tools = set(reg.list_tools())

    assert {"run_pipeline", "get_task_status"}.issubset(tools)

    run = reg.get("run_pipeline")
    assert run is not None
    # triggering a run mutates external state → analyze mode must auto-deny it
    assert run.mutates_external_state is True
    assert run.parameters["required"] == ["name"]

    status = reg.get("get_task_status")
    assert status is not None
    # polling status is read-only
    assert status.mutates_external_state is False
    assert status.parameters["required"] == ["task_chain_id"]


def test_admin_agent_yaml_grants_run_and_status_tools() -> None:
    from pathlib import Path

    from intellisource.config.pipeline_models import PipelineConfig

    path = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "pipelines"
        / "admin-agent.yaml"
    )
    cfg = PipelineConfig.from_yaml(str(path))

    assert "run_pipeline" in cfg.tools_allowed
    assert "get_task_status" in cfg.tools_allowed


def test_build_agent_runner_binds_run_dependencies() -> None:
    from unittest.mock import MagicMock

    from intellisource.agent.factory import build_agent_runner

    dispatcher = MagicMock()
    chain_factory = MagicMock()
    runner = build_agent_runner(
        session_factory=MagicMock(),
        llm_gateway=MagicMock(),
        collector_registry=MagicMock(),
        distributor=MagicMock(),
        search_engine_factory=MagicMock(),
        task_dispatcher=dispatcher,
        task_chain_repo_factory=chain_factory,
    )

    assert runner._tool_deps is not None
    assert runner._tool_deps.task_dispatcher is dispatcher
    assert runner._tool_deps.task_chain_repo_factory is chain_factory
