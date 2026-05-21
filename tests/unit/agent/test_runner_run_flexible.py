"""Tests for AgentRunner.run_flexible() consuming LLMResult from gateway.chat().

Covers R-001 (T-086 revision): confirms run_flexible() correctly accesses
LLMResult.content and LLMResult.metadata (tool_calls, finish_reason, usage)
rather than treating the return value as a plain dict.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.runner import AgentRunner
from intellisource.llm.gateway import LLMResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_registry(*tool_names: str) -> MagicMock:
    registry = MagicMock()
    tool_map = {name: AsyncMock(return_value={"result": name}) for name in tool_names}

    def _get(name: str):
        return tool_map.get(name)

    registry.get = MagicMock(side_effect=_get)
    registry.list_tools = MagicMock(return_value=list(tool_map.keys()))
    return registry


def _flexible_config(
    name: str, tools_allowed: list[str], max_steps: int = 5
) -> PipelineConfig:
    return PipelineConfig.from_dict(
        {
            "name": name,
            "mode": "flexible",
            "tools_allowed": tools_allowed,
            "tools_denied": [],
            "steps": [],
            "max_steps": max_steps,
            "on_failure": "skip",
        }
    )


# ---------------------------------------------------------------------------
# R-001: run_flexible consumes LLMResult shape (not plain dict)
# ---------------------------------------------------------------------------


class TestRunFlexibleConsumesLLMResult:
    """R-001: run_flexible() reads result.metadata instead of result.get(...)."""

    async def test_done_on_stop_finish_reason(self) -> None:
        """run_flexible stops when finish_reason='stop' in LLMResult.metadata."""
        llm_gw = AsyncMock()
        llm_gw.chat.return_value = LLMResult(
            content="Task complete.",
            metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
        )
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config("done-stop", tools_allowed=["web_search"])

        result = await runner.run_flexible(config, user_message="hello", session={})

        assert result["status"] == "success"
        assert result["steps_executed"] == 1
        llm_gw.chat.assert_awaited_once()

    async def test_done_when_tool_calls_empty(self) -> None:
        """run_flexible terminates when tool_calls is empty list (no pending calls)."""
        llm_gw = AsyncMock()
        llm_gw.chat.return_value = LLMResult(
            content="All done.",
            metadata={"tool_calls": [], "finish_reason": "tool_calls", "usage": {}},
        )
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config("done-empty-tools", tools_allowed=["web_search"])

        result = await runner.run_flexible(config, user_message="hi", session={})

        assert result["status"] == "success"
        llm_gw.chat.assert_awaited_once()

    async def test_tool_calls_in_metadata_dispatched_correctly(self) -> None:
        """tool_calls in LLMResult.metadata with tc.function object dispatches tool."""
        call_count = 0
        llm_gw = AsyncMock()

        async def _chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                tc = MagicMock()
                tc.function.name = "web_search"
                tc.function.arguments = '{"q": "ai"}'
                tc.id = "tc-001"
                return LLMResult(
                    content="",
                    metadata={
                        "tool_calls": [tc],
                        "finish_reason": "tool_calls",
                        "usage": {},
                    },
                )
            return LLMResult(
                content="done",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        llm_gw.chat.side_effect = _chat
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config("tool-dispatch", tools_allowed=["web_search"])

        result = await runner.run_flexible(config, user_message="search", session={})

        assert result["status"] == "success"
        assert call_count == 2
        assert len(result["results"]) == 1
        assert result["results"][0]["tool"] == "web_search"

    async def test_token_budget_tracked_via_metadata_usage(self) -> None:
        """Token budget read from LLMResult.metadata['usage']['total_tokens']."""
        call_count = 0
        llm_gw = AsyncMock()

        async def _chat(**kwargs):
            nonlocal call_count
            call_count += 1
            tc = MagicMock()
            tc.function.name = "web_search"
            tc.function.arguments = '{"q": "test"}'
            tc.id = f"tc-{call_count}"
            return LLMResult(
                content="",
                metadata={
                    "tool_calls": [tc],
                    "finish_reason": "tool_calls",
                    "usage": {"total_tokens": 6000},
                },
            )

        llm_gw.chat.side_effect = _chat
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "budget-via-metadata", tools_allowed=["web_search"], max_steps=20
        )

        result = await runner.run_flexible(
            config,
            user_message="search",
            session={},
            max_tokens_budget=10000,
        )

        assert result.get("budget_exhausted") is True
        assert result["status"] == "success"

    async def test_no_attribute_error_on_metadata_access(self) -> None:
        """LLMResult returned by chat() does not raise AttributeError on .metadata."""
        llm_gw = AsyncMock()
        llm_result = LLMResult(
            content="hello",
            metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
        )
        llm_gw.chat.return_value = llm_result
        registry = _make_tool_registry()
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config("no-attr-err", tools_allowed=[])

        result = await runner.run_flexible(config, user_message="hi", session={})
        assert result["status"] == "success"
