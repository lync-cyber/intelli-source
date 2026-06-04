"""FlexibleLoop human-in-the-loop approved-call pre-execution.

When the endpoint recovers approved calls from a confirm token, the loop
executes them up front — bypassing the confirm gate (that *is* the approval)
but still honouring deny — and seeds them into history so the next LLM turn
summarises the result.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from intellisource.agent.executors.flexible import FlexibleLoop
from intellisource.agent.runner import AgentMode
from intellisource.agent.tools.registry import AgentToolRegistry, PermissionLevel


def _config(**over: Any) -> SimpleNamespace:
    base = {
        "name": "admin-agent",
        "max_steps": 5,
        "tools_allowed": [],
        "tools_denied": [],
        "tool_permissions": {},
        "system_prompt": None,
        "max_tokens_budget": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _stop_gateway() -> Any:
    """LLM gateway whose chat() immediately stops with a summary answer."""

    async def chat(**_: Any) -> Any:
        return SimpleNamespace(
            content="已为你完成推送。",
            metadata={"finish_reason": "stop", "tool_calls": [], "usage": {}},
        )

    return SimpleNamespace(chat=chat)


def _loop(registry: AgentToolRegistry, gateway: Any) -> FlexibleLoop:
    async def _noop(*_: Any, **__: Any) -> None:
        return None

    async def _persist(**kwargs: Any) -> dict[str, Any]:
        return dict(kwargs)

    return FlexibleLoop(
        tool_registry=registry,
        llm_gateway=gateway,
        emit_pipeline_start=_noop,
        emit_tool_call=_noop,
        emit_llm_call=_noop,
        emit_pipeline_error=_noop,
        persist=_persist,
    )


@pytest.mark.asyncio
async def test_approved_confirm_tool_executes() -> None:
    executed: list[dict[str, Any]] = []

    async def _distribute(**kwargs: Any) -> dict[str, Any]:
        executed.append(kwargs)
        return {"status": "sent", "count": 1}

    registry = AgentToolRegistry()
    registry.register(
        name="distribute",
        description="push",
        parameters={"type": "object", "properties": {}},
        execute_fn=_distribute,
        permission_level=PermissionLevel.confirm,
        mutates_external_state=True,
    )

    result = await _loop(registry, _stop_gateway()).run(
        _config(),
        user_message="确认推送",
        session={},
        agent_mode=AgentMode.process,
        approved_calls=[{"tool": "distribute", "args": {"content_id": "c1"}}],
    )

    # the confirm gate is bypassed by the approval and the tool actually ran
    assert executed == [{"content_id": "c1"}]
    confirmed = [r for r in result["results"] if r.get("confirmed")]
    assert confirmed and confirmed[0]["output"] == {"status": "sent", "count": 1}


@pytest.mark.asyncio
async def test_approved_call_to_denied_tool_never_executes() -> None:
    executed: list[Any] = []

    async def _danger(**kwargs: Any) -> dict[str, Any]:
        executed.append(kwargs)
        return {"status": "ran"}

    registry = AgentToolRegistry()
    registry.register(
        name="danger",
        description="x",
        parameters={"type": "object", "properties": {}},
        execute_fn=_danger,
        permission_level=PermissionLevel.deny,
    )

    result = await _loop(registry, _stop_gateway()).run(
        _config(),
        user_message="run it",
        session={},
        agent_mode=AgentMode.process,
        approved_calls=[{"tool": "danger", "args": {}}],
    )

    # a forged approval cannot run a denied tool
    assert executed == []
    blocked = [
        r for r in result["results"] if r.get("status") == "denied_by_permission"
    ]
    assert blocked and blocked[0]["tool"] == "danger"


@pytest.mark.asyncio
async def test_no_approved_calls_runs_normal_loop() -> None:
    registry = AgentToolRegistry()
    registry.register(
        name="distribute",
        description="push",
        parameters={"type": "object", "properties": {}},
        execute_fn=_unused_execute,
        permission_level=PermissionLevel.confirm,
    )

    result = await _loop(registry, _stop_gateway()).run(
        _config(),
        user_message="hi",
        session={},
        agent_mode=AgentMode.process,
        approved_calls=None,
    )

    # nothing pre-executed; the loop just produced the summary
    assert all(not r.get("confirmed") for r in result["results"])


async def _unused_execute(**_: Any) -> dict[str, Any]:
    raise AssertionError("tool must not be executed")
