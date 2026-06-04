"""Tests for F-07 (unknown-tool protocol closure) and F-08 (strict degraded raises).

F-07: When LLM requests an unknown tool in flexible mode the runner must append
      a role='tool' error message so the next LLM turn is not left with an
      unclosed tool_call, which would cause a 400 from the provider.

F-08: When a tool returns {"status": "degraded"} in strict mode the runner
      must raise ToolDegradedError rather than silently recording it as success.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.agent.runner import AgentRunner, ToolDegradedError
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.llm.gateway import LLMResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm_with_tool_call(tool_name: str, call_id: str = "call_xyz") -> LLMResult:
    """LLMResult asking to call a tool (dict-style tool call)."""
    return LLMResult(
        content="",
        metadata={
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": "{}"},
                }
            ],
            "finish_reason": "tool_calls",
            "usage": {},
        },
    )


def _llm_done(content: str = "done") -> LLMResult:
    return LLMResult(
        content=content,
        metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
    )


def _flexible_config(tools_allowed: list[str] | None = None) -> PipelineConfig:
    return PipelineConfig.from_dict(
        {
            "name": "test-flexible",
            "mode": "flexible",
            "tools_allowed": tools_allowed or [],
            "tools_denied": [],
            "steps": [],
            "max_steps": 5,
        }
    )


def _strict_config(
    tool_name: str = "my_tool", on_failure: str = "abort"
) -> PipelineConfig:
    return PipelineConfig.from_dict(
        {
            "name": "test-strict",
            "mode": "strict",
            "steps": [{"tool": tool_name, "params": {}}],
            "max_steps": 5,
            "on_failure": on_failure,
        }
    )


def _make_registry(tools: dict[str, Any]) -> MagicMock:
    """Registry whose .get() returns None for unknown tools."""
    registry = MagicMock()
    registry.get = MagicMock(side_effect=lambda name: tools.get(name))
    registry.list_tools = MagicMock(return_value=list(tools.keys()))
    return registry


# ---------------------------------------------------------------------------
# F-07 tests
# ---------------------------------------------------------------------------


class TestFlexibleUnknownToolClosesProtocol:
    """F-07: unknown tool must produce a role='tool' error message."""

    @pytest.mark.asyncio
    async def test_unknown_tool_appends_error_tool_message(self) -> None:
        """The messages list must contain a role='tool' entry for the unknown call."""
        # LLM first asks for 'ghost_tool' (not in registry), then stops.
        llm = AsyncMock()
        llm.chat.side_effect = [
            _llm_with_tool_call("ghost_tool", call_id="call_abc"),
            _llm_done("done"),
        ]

        registry = _make_registry({})  # empty — ghost_tool unknown
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)

        result = await runner.run_flexible(
            _flexible_config(), user_message="go", session={}
        )

        assert result["status"] == "success"
        # Verify second LLM call received a tool-role message closing the call
        second_call_messages: list[dict] = llm.chat.call_args_list[1].kwargs["messages"]
        tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1, (
            "Expected exactly one tool-role message to close the protocol"
        )
        tool_msg = tool_msgs[0]
        assert tool_msg["tool_call_id"] == "call_abc"
        payload = json.loads(tool_msg["content"])
        assert payload["error"] == "unknown_tool"
        assert payload["name"] == "ghost_tool"

    @pytest.mark.asyncio
    async def test_unknown_tool_recorded_in_tool_results(self) -> None:
        """tool_results in the return value must reflect the unknown-tool error."""
        llm = AsyncMock()
        llm.chat.side_effect = [
            _llm_with_tool_call("no_such_tool", call_id="call_001"),
            _llm_done(),
        ]
        registry = _make_registry({})
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)

        result = await runner.run_flexible(
            _flexible_config(), user_message="hi", session={}
        )

        assert any(
            r.get("error") == "unknown_tool" and r["tool"] == "no_such_tool"
            for r in result["results"]
        ), "tool_results must contain an error entry for the unknown tool"

    @pytest.mark.asyncio
    async def test_unknown_tool_does_not_abort_loop(self) -> None:
        """Loop continues after unknown-tool and can still deliver a final answer."""
        llm = AsyncMock()
        llm.chat.side_effect = [
            _llm_with_tool_call("phantom", call_id="call_z"),
            _llm_done("final answer here"),
        ]
        registry = _make_registry({})
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)

        result = await runner.run_flexible(
            _flexible_config(), user_message="run", session={}
        )

        assert result.get("final_answer") == "final answer here"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_known_and_unknown_tools_in_same_turn(self) -> None:
        """Both known and unknown tools in one turn each get proper protocol closure."""

        async def _real_tool(**kwargs: Any) -> dict[str, Any]:
            return {"ok": True}

        llm = AsyncMock()
        llm.chat.side_effect = [
            LLMResult(
                content="",
                metadata={
                    "tool_calls": [
                        {
                            "id": "call_known",
                            "type": "function",
                            "function": {"name": "real_tool", "arguments": "{}"},
                        },
                        {
                            "id": "call_ghost",
                            "type": "function",
                            "function": {"name": "ghost_tool", "arguments": "{}"},
                        },
                    ],
                    "finish_reason": "tool_calls",
                    "usage": {},
                },
            ),
            _llm_done("ok"),
        ]
        registry = _make_registry({"real_tool": AsyncMock(side_effect=_real_tool)})
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)

        result = await runner.run_flexible(
            _flexible_config(tools_allowed=["real_tool"]),
            user_message="go",
            session={},
        )

        second_messages: list[dict] = llm.chat.call_args_list[1].kwargs["messages"]
        tool_msgs = [m for m in second_messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 2

        ghost_msg = next(m for m in tool_msgs if m["tool_call_id"] == "call_ghost")
        payload = json.loads(ghost_msg["content"])
        assert payload["error"] == "unknown_tool"

        known_msg = next(m for m in tool_msgs if m["tool_call_id"] == "call_known")
        assert json.loads(known_msg["content"]) == {"ok": True}
        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# F-08 tests
# ---------------------------------------------------------------------------


class TestStrictDegradedRaises:
    """F-08: strict mode must raise ToolDegradedError on status='degraded'."""

    @pytest.mark.asyncio
    async def test_degraded_result_raises_tool_degraded_error(self) -> None:
        """ToolDegradedError is raised and propagates out of run_strict."""
        degraded_tool = AsyncMock(
            return_value={"status": "degraded", "reason": "upstream unavailable"}
        )
        registry = _make_registry({"my_tool": degraded_tool})
        runner = AgentRunner(tool_registry=registry)

        with pytest.raises(ToolDegradedError, match="degraded"):
            await runner.run_strict(
                _strict_config("my_tool"), params={}, tool_deps=None
            )

    @pytest.mark.asyncio
    async def test_degraded_error_message_contains_tool_name_and_reason(self) -> None:
        """The error message must include both the tool name and the reason."""
        degraded_tool = AsyncMock(
            return_value={"status": "degraded", "reason": "timeout"}
        )
        registry = _make_registry({"my_tool": degraded_tool})
        runner = AgentRunner(tool_registry=registry)

        with pytest.raises(ToolDegradedError) as exc_info:
            await runner.run_strict(
                _strict_config("my_tool"), params={}, tool_deps=None
            )

        assert "my_tool" in str(exc_info.value)
        assert "timeout" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_ok_result_does_not_raise(self) -> None:
        """A tool returning status='ok' must not raise ToolDegradedError."""
        ok_tool = AsyncMock(return_value={"status": "ok", "data": "result"})
        registry = _make_registry({"my_tool": ok_tool})
        runner = AgentRunner(tool_registry=registry)

        result = await runner.run_strict(
            _strict_config("my_tool"), params={}, tool_deps=None
        )

        assert result["status"] == "success"
        assert result["results"][0]["output"] == {"status": "ok", "data": "result"}

    @pytest.mark.asyncio
    async def test_flexible_mode_degraded_does_not_raise(self) -> None:
        """In flexible mode a degraded tool result is passed to LLM, not raised."""
        degraded_tool = AsyncMock(
            return_value={"status": "degraded", "reason": "overloaded"}
        )
        llm = AsyncMock()
        llm.chat.side_effect = [
            _llm_with_tool_call("my_tool", call_id="call_deg"),
            _llm_done("handled gracefully"),
        ]
        registry = _make_registry({"my_tool": degraded_tool})
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)

        # Must NOT raise — flexible passes the degraded result content to LLM
        result = await runner.run_flexible(
            _flexible_config(tools_allowed=["my_tool"]),
            user_message="run",
            session={},
        )

        assert result["status"] == "success"
        # The degraded result should have been serialized into the tool message
        second_messages: list[dict] = llm.chat.call_args_list[1].kwargs["messages"]
        tool_msgs = [m for m in second_messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        payload = json.loads(tool_msgs[0]["content"])
        assert payload["status"] == "degraded"
