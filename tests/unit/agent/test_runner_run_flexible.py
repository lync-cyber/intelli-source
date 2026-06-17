"""Tests for AgentRunner.run_flexible() consuming LLMResult from gateway.chat().

Confirms run_flexible() correctly accesses LLMResult.content and
LLMResult.metadata (tool_calls, finish_reason, usage) rather than treating
the return value as a plain dict.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from intellisource.agent.executors.flexible import _validate_history
from intellisource.agent.runner import AgentRunner
from intellisource.config.pipeline_models import PipelineConfig
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
# run_flexible consumes LLMResult shape (not plain dict)
# ---------------------------------------------------------------------------


class TestRunFlexibleConsumesLLMResult:
    """run_flexible() reads result.metadata instead of result.get(...)."""

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

    async def test_config_default_budget_stops_before_tool_dispatch(self) -> None:
        """P1-2: config-level max_tokens_budget prevents costly tool fan-out."""
        llm_gw = AsyncMock()
        llm_gw.chat.return_value = LLMResult(
            content="",
            metadata={
                "tool_calls": [
                    {"name": "web_search", "arguments": {"q": "ai"}, "id": "tc-1"}
                ],
                "finish_reason": "tool_calls",
                "usage": {"total_tokens": 150},
            },
        )
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = PipelineConfig.from_dict(
            {
                "name": "budget-from-config",
                "mode": "flexible",
                "tools_allowed": ["web_search"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 5,
                "max_tokens_budget": 100,
                "on_failure": "skip",
            }
        )

        result = await runner.run_flexible(config, user_message="search", session={})

        assert result["status"] == "success"
        assert result["budget_exhausted"] is True
        assert result["tokens_used"] == 150
        assert result["results"] == []
        registry.get("web_search").assert_not_called()

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

    async def test_tools_are_openai_function_schema(self) -> None:
        """run_flexible passes LLMGateway-valid function tool descriptors."""
        llm_gw = AsyncMock()
        llm_gw.chat.return_value = LLMResult(
            content="done",
            metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
        )
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config("schema", tools_allowed=["web_search"])

        await runner.run_flexible(config, user_message="hello", session={})

        tools = llm_gw.chat.await_args.kwargs["tools"]
        assert tools == [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    async def test_session_history_is_passed_to_llm_messages(self) -> None:
        """run_flexible includes prior chat history before the current user turn."""
        llm_gw = AsyncMock()
        llm_gw.chat.return_value = LLMResult(
            content="done",
            metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
        )
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config("history", tools_allowed=["web_search"])

        await runner.run_flexible(
            config,
            user_message="current",
            session={
                "messages": [
                    {"role": "user", "content": "history-q"},
                    {"role": "assistant", "content": "history-a"},
                ]
            },
        )

        messages = llm_gw.chat.await_args.kwargs["messages"]
        assert messages[-3:] == [
            {"role": "user", "content": "history-q"},
            {"role": "assistant", "content": "history-a"},
            {"role": "user", "content": "current"},
        ]

    async def test_final_llm_answer_is_returned_when_no_tools(self) -> None:
        """P1-8: final assistant content is not dropped from flexible result."""
        llm_gw = AsyncMock()
        llm_gw.chat.return_value = LLMResult(
            content="final answer",
            metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
        )
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config("final-answer", tools_allowed=["web_search"])

        result = await runner.run_flexible(config, user_message="hello", session={})

        assert result["final_answer"] == "final answer"

    async def test_default_system_prompt_injected_when_config_has_none(self) -> None:
        """Non-stream run_flexible injects the IntelliSource identity prompt.

        Mirrors the streaming path (run_flexible_stream), which falls back to
        ``_default_system_prompt`` when the pipeline declares no system_prompt.
        Without parity here, the CLI (non-stream /search/chat) loses its
        identity while the web (stream) keeps it — the model drifts to a
        generic ``我是你的智能助手`` answer. The tool list is NOT rendered into
        the prompt — callable tools reach the model via the tools= param.
        """
        captured: dict[str, Any] = {}

        async def _chat(*, messages: list[dict[str, Any]], **_: Any) -> LLMResult:
            captured["messages"] = messages
            return LLMResult(
                content="hi",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        llm_gw = AsyncMock()
        llm_gw.chat = AsyncMock(side_effect=_chat)
        registry = _make_tool_registry("search", "get_content_detail")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "no-prompt", tools_allowed=["search", "get_content_detail"]
        )

        await runner.run_flexible(config, user_message="你是谁", session={})

        system_msg = captured["messages"][0]
        assert system_msg["role"] == "system"
        text = system_msg["content"]
        assert "IntelliSource" in text
        assert "get_content_detail" not in text, (
            "tool list must not be rendered into the system prompt; tools reach "
            "the model via the tools= param"
        )

    async def test_configured_system_prompt_takes_precedence(self) -> None:
        """An explicit pipeline system_prompt is used verbatim (no fallback)."""
        captured: dict[str, Any] = {}

        async def _chat(*, messages: list[dict[str, Any]], **_: Any) -> LLMResult:
            captured["messages"] = messages
            return LLMResult(
                content="ok",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        llm_gw = AsyncMock()
        llm_gw.chat = AsyncMock(side_effect=_chat)
        registry = _make_tool_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = PipelineConfig.from_dict(
            {
                "name": "custom-prompt",
                "mode": "flexible",
                "tools_allowed": ["search"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
                "system_prompt": "CUSTOM-PROMPT-SENTINEL",
            }
        )

        await runner.run_flexible(config, user_message="hi", session={})

        assert captured["messages"][0]["content"] == "CUSTOM-PROMPT-SENTINEL"

    async def test_chat_exception_degrades_to_error_result(self) -> None:
        """P3: a failing non-stream chat() returns an error result, never raises.

        The streaming path already catches a failing turn and emits an error
        event; the non-stream path must reach the same place instead of letting
        the exception propagate to the API route as an unhandled 500 (which also
        skips persistence). The loop counts the failed turn as one step.
        """
        llm_gw = AsyncMock()
        llm_gw.chat = AsyncMock(side_effect=RuntimeError("upstream blew up"))
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config("chat-fail", tools_allowed=["web_search"])

        result = await runner.run_flexible(config, user_message="hi", session={})

        assert result["status"] == "error"
        assert result["steps_executed"] == 1
        assert "upstream blew up" in result["detail"]
        llm_gw.chat.assert_awaited_once()

    async def test_tool_failure_message_is_structured_and_truncated(self) -> None:
        """P5: a failing tool yields a JSON tool message, not raw 'Error: ...'.

        Mixing a bare ``Error: {exc}`` string with the JSON the deny/preview
        branches emit makes the model parse inconsistently; the raw exception is
        also truncated so a long message carrying connection strings / internal
        paths is not replayed verbatim into history or the returned results.
        """
        long_msg = "boom " * 100  # 500 chars, well over the 200-char cap
        call_count = 0
        llm_gw = AsyncMock()

        async def _chat(**_: Any) -> LLMResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResult(
                    content="",
                    metadata={
                        "tool_calls": [
                            {
                                "name": "web_search",
                                "arguments": {"q": "ai"},
                                "id": "tc-1",
                            }
                        ],
                        "finish_reason": "tool_calls",
                        "usage": {},
                    },
                )
            return LLMResult(
                content="done",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        llm_gw.chat.side_effect = _chat
        failing_tool = AsyncMock(side_effect=RuntimeError(long_msg))
        registry = MagicMock()
        registry.get = MagicMock(
            side_effect=lambda n: failing_tool if n == "web_search" else None
        )
        registry.list_tools = MagicMock(return_value=["web_search"])
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config("tool-fail-fmt", tools_allowed=["web_search"])

        result = await runner.run_flexible(config, user_message="search", session={})

        second_messages = llm_gw.chat.await_args_list[1].kwargs["messages"]
        tool_msg = second_messages[-1]
        assert tool_msg["role"] == "tool"
        assert tool_msg["content"].lstrip().startswith("{"), (
            "tool error must be structured JSON, not a raw 'Error: ...' string"
        )
        payload = json.loads(tool_msg["content"])
        assert payload["status"] == "error"
        assert payload["tool"] == "web_search"
        assert len(payload["error"]) <= 200

        tool_result = result["results"][0]
        assert tool_result["error"] is not None
        assert len(tool_result["error"]) <= 200

    async def test_slow_tool_times_out_and_is_reported_as_error(self) -> None:
        """P2: a tool exceeding tool_timeout_s is cancelled and reported, not hung.

        Without a per-call deadline a slow external-IO tool blocks the whole
        run indefinitely. The timed-out call is fed back as a tool error so the
        loop recovers and the next LLM turn still runs.
        """
        call_count = 0
        llm_gw = AsyncMock()

        async def _chat(**_: Any) -> LLMResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResult(
                    content="",
                    metadata={
                        "tool_calls": [
                            {"name": "web_search", "arguments": {"q": "ai"}, "id": "t1"}
                        ],
                        "finish_reason": "tool_calls",
                        "usage": {},
                    },
                )
            return LLMResult(
                content="done",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        llm_gw.chat.side_effect = _chat

        async def _slow(**_: Any) -> dict[str, Any]:
            await asyncio.sleep(0.2)
            return {"result": "never"}

        slow_tool = AsyncMock(side_effect=_slow)
        registry = MagicMock()
        registry.get = MagicMock(
            side_effect=lambda n: slow_tool if n == "web_search" else None
        )
        registry.list_tools = MagicMock(return_value=["web_search"])
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = PipelineConfig.from_dict(
            {
                "name": "slow-tool",
                "mode": "flexible",
                "tools_allowed": ["web_search"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
                "tool_timeout_s": 0.01,
            }
        )

        result = await runner.run_flexible(config, user_message="x", session={})

        tool_result = result["results"][0]
        assert tool_result["output"] is None
        assert tool_result.get("error") is not None
        assert call_count == 2

    async def test_slow_chat_times_out_and_degrades_to_error(self) -> None:
        """P2: a non-stream chat() exceeding llm_timeout_s degrades to an error.

        A hung LLM call must not block the run forever; the deadline turns it
        into the same error result a raised exception produces (P3).
        """

        async def _slow_chat(**_: Any) -> LLMResult:
            await asyncio.sleep(0.2)
            return LLMResult(
                content="late",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        llm_gw = AsyncMock()
        llm_gw.chat = AsyncMock(side_effect=_slow_chat)
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = PipelineConfig.from_dict(
            {
                "name": "slow-chat",
                "mode": "flexible",
                "tools_allowed": ["web_search"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
                "llm_timeout_s": 0.01,
            }
        )

        result = await runner.run_flexible(config, user_message="x", session={})

        assert result["status"] == "error"
        # _describe_exc(TimeoutError()) falls back to the type name (str() is empty)
        assert result["detail"] == "TimeoutError"

    async def test_session_history_drops_unpaired_tool_messages(self) -> None:
        """P8: rehydrated history keeps only clean user/assistant text turns.

        A persisted tool message (or an assistant carrying tool_calls) cannot be
        re-paired across a session boundary; surfacing a bare tool message would
        orphan the provider's tool-call protocol and get the request rejected.
        """
        llm_gw = AsyncMock()
        llm_gw.chat.return_value = LLMResult(
            content="done",
            metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
        )
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config("hist-orphan", tools_allowed=["web_search"])

        await runner.run_flexible(
            config,
            user_message="current",
            session={
                "messages": [
                    {"role": "user", "content": "q1"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "old",
                                "type": "function",
                                "function": {"name": "web_search", "arguments": "{}"},
                            }
                        ],
                    },
                    {"role": "tool", "content": '{"r": 1}', "tool_call_id": "old"},
                    {"role": "assistant", "content": "a1"},
                ]
            },
        )

        sent = llm_gw.chat.await_args.kwargs["messages"]
        roles = [m["role"] for m in sent]
        assert "tool" not in roles
        assert all(not m.get("tool_calls") for m in sent if m["role"] == "assistant")
        text_turns = [
            (m["role"], m["content"])
            for m in sent
            if m["role"] in ("user", "assistant")
        ]
        assert ("user", "q1") in text_turns
        assert ("assistant", "a1") in text_turns
        assert ("user", "current") in text_turns

    async def test_stop_finish_reason_with_tool_calls_still_executes(self) -> None:
        """P8: tool_calls run even when finish_reason='stop'.

        Breaking on 'stop' while tool_calls are pending would leave an assistant
        tool_calls message with no matching tool response — malformed history.
        """
        call_count = 0
        llm_gw = AsyncMock()

        async def _chat(**_: Any) -> LLMResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResult(
                    content="",
                    metadata={
                        "tool_calls": [
                            {
                                "name": "web_search",
                                "arguments": {"q": "ai"},
                                "id": "tc-1",
                            }
                        ],
                        "finish_reason": "stop",
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
        config = _flexible_config("stop-with-tools", tools_allowed=["web_search"])

        result = await runner.run_flexible(config, user_message="x", session={})

        assert call_count == 2
        assert len(result["results"]) == 1
        assert result["results"][0]["tool"] == "web_search"
        second_messages = llm_gw.chat.await_args_list[1].kwargs["messages"]
        assert second_messages[-2]["role"] == "assistant"
        assert second_messages[-2]["tool_calls"][0]["id"] == "tc-1"
        assert second_messages[-1]["role"] == "tool"
        assert second_messages[-1]["tool_call_id"] == "tc-1"

    async def test_tool_result_roundtrip_has_assistant_tool_call_message(self) -> None:
        """P1-8: tool result messages keep the provider-required protocol chain."""
        call_count = 0
        llm_gw = AsyncMock()

        async def _chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResult(
                    content="",
                    metadata={
                        "tool_calls": [
                            {
                                "name": "web_search",
                                "arguments": {"q": "ai"},
                                "id": "tc-1",
                            }
                        ],
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
        config = _flexible_config("tool-protocol", tools_allowed=["web_search"])

        await runner.run_flexible(config, user_message="search", session={})

        second_messages = llm_gw.chat.await_args_list[1].kwargs["messages"]
        assert second_messages[-2]["role"] == "assistant"
        assert second_messages[-2]["tool_calls"][0]["id"] == "tc-1"
        assert second_messages[-1]["role"] == "tool"
        assert second_messages[-1]["tool_call_id"] == "tc-1"


class TestRunFlexibleAppliesCompression:
    """P10: _drive runs the gateway compressor before each turn."""

    async def test_compressed_history_is_what_reaches_the_llm(self) -> None:
        class _Gw:
            def __init__(self) -> None:
                self.seen: list[list[dict[str, Any]]] = []

            async def compress_if_needed(
                self,
                messages: list[dict[str, Any]],
                task_type: str = "chat",
                precomputed_total: int | None = None,
            ) -> list[dict[str, Any]]:
                return [{"role": "system", "content": "COMPRESSED"}, messages[-1]]

            async def chat(
                self, *, messages: list[dict[str, Any]], **_: Any
            ) -> LLMResult:
                self.seen.append(list(messages))
                return LLMResult(
                    content="done",
                    metadata={
                        "tool_calls": None,
                        "finish_reason": "stop",
                        "usage": {},
                    },
                )

        gw = _Gw()
        registry = _make_tool_registry("web_search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=gw)
        config = _flexible_config("compress", tools_allowed=["web_search"])

        result = await runner.run_flexible(config, user_message="hello", session={})

        assert result["status"] == "success"
        assert gw.seen[0][0] == {"role": "system", "content": "COMPRESSED"}
        assert gw.seen[0][-1] == {"role": "user", "content": "hello"}


class _FakeStream:
    """Stateful async-gen stub for stream_complete: records aclose, can hang/raise.

    Mirrors the chunk contract _run_turn consumes — content deltas as
    ``{"content": ...}`` and a terminal ``{"done": True, "metadata": {...}}`` —
    so the streaming path is exercised over a faithful shape, not a constant.
    """

    def __init__(
        self,
        chunks: list[dict[str, Any]],
        *,
        hang_after: int | None = None,
        raise_after: int | None = None,
        aclose_raises: bool = False,
    ) -> None:
        self._chunks = chunks
        self._i = 0
        self._hang_after = hang_after
        self._raise_after = raise_after
        self._aclose_raises = aclose_raises
        self.aclosed = False

    def __aiter__(self) -> _FakeStream:
        return self

    async def __anext__(self) -> dict[str, Any]:
        idx = self._i
        if self._hang_after is not None and idx >= self._hang_after:
            await asyncio.sleep(10)  # outlives any test deadline → cut by wait_for
        if self._raise_after is not None and idx >= self._raise_after:
            raise RuntimeError("stream exploded")
        if self._i >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._i]
        self._i += 1
        return chunk

    async def aclose(self) -> None:
        self.aclosed = True
        if self._aclose_raises:
            raise RuntimeError("aclose blew up")


class _StreamGateway:
    """Gateway stub exposing only stream_complete (no compress_if_needed)."""

    def __init__(self, stream: _FakeStream) -> None:
        self._stream = stream

    def stream_complete(
        self, *, messages: list[dict[str, Any]], tools: Any
    ) -> _FakeStream:
        return self._stream


def _done_chunk(content_tokens: int = 2) -> dict[str, Any]:
    return {
        "done": True,
        "metadata": {
            "input_tokens": 5,
            "output_tokens": content_tokens,
            "tool_calls": None,
            "finish_reason": "stop",
            "model": "m",
        },
    }


class TestRunFlexibleStreamTimeout:
    """run_flexible_stream's per-chunk timeout / error / cleanup paths."""

    async def test_stream_completes_and_closes_generator(self) -> None:
        """Healthy stream surfaces token deltas, a success done event, aclose."""
        stream = _FakeStream([{"content": "Hel"}, {"content": "lo"}, _done_chunk()])
        runner = AgentRunner(
            tool_registry=_make_tool_registry("web_search"),
            llm_gateway=_StreamGateway(stream),
        )
        config = _flexible_config("stream-ok", tools_allowed=["web_search"])

        events = [
            e
            async for e in runner.run_flexible_stream(
                config, user_message="hi", session={}
            )
        ]

        deltas = [e["delta"] for e in events if e["type"] == "token"]
        assert deltas == ["Hel", "lo"]
        assert events[-1]["type"] == "done"
        assert events[-1]["metadata"]["status"] == "success"
        assert events[-1]["metadata"]["final_answer"] == "Hello"
        assert stream.aclosed is True

    async def test_stalled_stream_times_out_and_closes_generator(self) -> None:
        """A chunk read exceeding llm_timeout_s degrades to an error event.

        The stalled ``__anext__`` is cut by the per-read deadline and the
        generator is still closed, so a hung upstream never blocks the run.
        """
        stream = _FakeStream([_done_chunk()], hang_after=0)
        runner = AgentRunner(
            tool_registry=_make_tool_registry("web_search"),
            llm_gateway=_StreamGateway(stream),
        )
        config = PipelineConfig.from_dict(
            {
                "name": "stream-stall",
                "mode": "flexible",
                "tools_allowed": ["web_search"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
                "llm_timeout_s": 0.05,
            }
        )

        events = [
            e
            async for e in runner.run_flexible_stream(
                config, user_message="hi", session={}
            )
        ]

        assert events[-1]["type"] == "error"
        assert "Timeout" in events[-1]["detail"]
        assert stream.aclosed is True

    async def test_stream_raises_midway_does_not_inject_partial(self) -> None:
        """A mid-stream exception ends the turn in error without keeping partial.

        Partial content already streamed must not be promoted to final_answer —
        an interrupted turn has no complete answer to persist.
        """
        stream = _FakeStream([{"content": "par"}], raise_after=1)
        runner = AgentRunner(
            tool_registry=_make_tool_registry("web_search"),
            llm_gateway=_StreamGateway(stream),
        )
        config = _flexible_config("stream-boom", tools_allowed=["web_search"])

        events = [
            e
            async for e in runner.run_flexible_stream(
                config, user_message="hi", session={}
            )
        ]

        assert any(e["type"] == "token" and e["delta"] == "par" for e in events)
        assert events[-1]["type"] == "error"
        assert events[-1]["detail"] == "stream exploded"
        assert "final_answer" not in events[-1]["metadata"]
        assert stream.aclosed is True

    async def test_aclose_failure_does_not_break_the_run(self) -> None:
        """A raising aclose during cleanup is swallowed, run still done."""
        stream = _FakeStream([{"content": "ok"}, _done_chunk()], aclose_raises=True)
        runner = AgentRunner(
            tool_registry=_make_tool_registry("web_search"),
            llm_gateway=_StreamGateway(stream),
        )
        config = _flexible_config("stream-aclose-boom", tools_allowed=["web_search"])

        events = [
            e
            async for e in runner.run_flexible_stream(
                config, user_message="hi", session={}
            )
        ]

        assert events[-1]["type"] == "done"
        assert events[-1]["metadata"]["status"] == "success"
        assert stream.aclosed is True


class TestDriveIncrementalTokenAccounting:
    """_drive feeds compress_if_needed an incremental token total."""

    async def test_drive_passes_precomputed_total_to_compress(self) -> None:
        """The loop hands its running token estimate to the compactor.

        Without it the compactor re-scans the whole history every turn; the
        precomputed total is what lets it skip that per-turn full scan.
        """
        seen: dict[str, Any] = {}

        class _GW:
            async def chat(self, **_: Any) -> LLMResult:
                return LLMResult(
                    content="done",
                    metadata={
                        "tool_calls": None,
                        "finish_reason": "stop",
                        "usage": {},
                    },
                )

            def estimate_tokens(self, text: str, model: str) -> int:
                return len(str(text))

            def estimate_history_tokens(
                self, messages: list[dict[str, Any]], task_type: str = "chat"
            ) -> int:
                return sum(len(str(m.get("content", ""))) for m in messages)

            async def compress_if_needed(
                self,
                messages: list[dict[str, Any]],
                task_type: str = "chat",
                precomputed_total: int | None = None,
            ) -> list[dict[str, Any]]:
                seen["precomputed_total"] = precomputed_total
                return messages

        runner = AgentRunner(
            tool_registry=_make_tool_registry("web_search"),
            llm_gateway=_GW(),
        )
        config = _flexible_config("incremental-tokens", tools_allowed=["web_search"])

        await runner.run_flexible(config, user_message="hello world", session={})

        assert seen["precomputed_total"] is not None
        assert seen["precomputed_total"] >= len("hello world")


class TestConcurrentToolCalls:
    """P11: independent tool_calls in one turn run concurrently, results in order."""

    async def test_independent_tool_calls_run_concurrently(self) -> None:
        """Two tools in one turn run concurrently; result order is preserved.

        ``first`` blocks on a barrier only ``second`` releases, so it completes
        solely when both run concurrently. Sequential execution would leave
        ``first`` waiting until its own deadline and error out.
        """
        barrier = asyncio.Event()

        async def first(**_: Any) -> dict[str, Any]:
            await asyncio.wait_for(barrier.wait(), timeout=1.0)
            return {"ok": "first"}

        async def second(**_: Any) -> dict[str, Any]:
            barrier.set()
            return {"ok": "second"}

        tools: dict[str, Any] = {"first": first, "second": second}
        registry = MagicMock()
        registry.get = MagicMock(side_effect=lambda n: tools.get(n))
        registry.list_tools = MagicMock(return_value=list(tools))

        class _TwoToolGateway:
            def __init__(self) -> None:
                self.calls = 0

            async def chat(self, **_: Any) -> LLMResult:
                self.calls += 1
                if self.calls == 1:
                    return LLMResult(
                        content="",
                        metadata={
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "first", "arguments": "{}"},
                                },
                                {
                                    "id": "c2",
                                    "type": "function",
                                    "function": {"name": "second", "arguments": "{}"},
                                },
                            ],
                            "finish_reason": "tool_calls",
                            "usage": {},
                        },
                    )
                return LLMResult(
                    content="done",
                    metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
                )

        runner = AgentRunner(tool_registry=registry, llm_gateway=_TwoToolGateway())
        config = _flexible_config("concurrent", tools_allowed=["first", "second"])

        result = await runner.run_flexible(config, user_message="go", session={})

        outputs = [r for r in result["results"] if "output" in r]
        by_tool = {r["tool"]: r["output"] for r in outputs}
        assert by_tool["first"] == {"ok": "first"}
        assert by_tool["second"] == {"ok": "second"}
        # the original tool_call order is preserved in the results
        exec_order = [r["tool"] for r in outputs if r["tool"] in ("first", "second")]
        assert exec_order == ["first", "second"]


class TestValidateHistory:
    """P8: _validate_history flags broken tool-call pairing, passes valid chains."""

    def test_paired_tool_call_chain_is_valid(self) -> None:
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "a", "type": "function", "function": {}}],
            },
            {"role": "tool", "content": "{}", "tool_call_id": "a"},
            {"role": "assistant", "content": "done"},
        ]
        assert _validate_history(messages) == []

    def test_unanswered_tool_call_is_flagged(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "a", "type": "function", "function": {}}],
            },
            {"role": "assistant", "content": "skipped the tool"},
        ]
        problems = _validate_history(messages)
        assert any("unanswered" in p for p in problems)

    def test_orphan_tool_message_is_flagged(self) -> None:
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "{}", "tool_call_id": "ghost"},
        ]
        problems = _validate_history(messages)
        assert any("no open tool_call" in p for p in problems)

    def test_multi_tool_calls_all_answered_is_valid(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "a", "type": "function", "function": {}},
                    {"id": "b", "type": "function", "function": {}},
                ],
            },
            {"role": "tool", "content": "{}", "tool_call_id": "a"},
            {"role": "tool", "content": "{}", "tool_call_id": "b"},
        ]
        assert _validate_history(messages) == []
