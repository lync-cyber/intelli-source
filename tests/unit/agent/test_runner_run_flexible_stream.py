"""Tests for AgentRunner.run_flexible_stream() — RAG-aware SSE streaming.

Covers:
  - simple-no-tools path: one stream_complete turn → token events + done
  - with-tools path: stream_complete(tool_calls) → search → stream_complete(answer);
    emits step events and (when search returns items) a sources event
  - tool-borne answer recovered when the terminal turn streams no free text
  - budget exhaustion: no LLM call; done carries budget_exhausted=True
  - streaming turn failure path: yields {"type": "error", ...}
  - preview agent mode: explicitly rejected by run_stream

Each turn streams through ``llm_gateway.stream_complete(messages=, tools=)``; the
turn's terminal chunk metadata carries the accumulated ``tool_calls`` and
``finish_reason``, so a turn that ends in a final answer streams it directly
without a second LLM call.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.agent.runner import AgentRunner
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.core.errors import IntelliSourceError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AsyncIter:
    def __init__(self, items: list[Any]) -> None:
        self._it = iter(items)

    def __aiter__(self) -> "_AsyncIter":
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _make_registry(
    *tool_names: str, tool_results: dict[str, Any] | None = None
) -> MagicMock:
    registry = MagicMock()
    overrides = tool_results or {}
    tool_map: dict[str, AsyncMock] = {}
    for name in tool_names:
        result = overrides.get(name, {"result": name})
        tool_map[name] = AsyncMock(return_value=result)

    def _get(name: str) -> Any:
        return tool_map.get(name)

    registry.get = MagicMock(side_effect=_get)
    registry.list_tools = MagicMock(return_value=list(tool_map.keys()))
    return registry


def _flex_config(
    name: str, tools_allowed: list[str], max_steps: int = 5, agent_mode: str = "process"
) -> PipelineConfig:
    return PipelineConfig.from_dict(
        {
            "name": name,
            "mode": "flexible",
            "agent_mode": agent_mode,
            "tools_allowed": tools_allowed,
            "tools_denied": [],
            "steps": [],
            "max_steps": max_steps,
            "on_failure": "skip",
        }
    )


def _token(content: str) -> dict[str, Any]:
    return {"content": content, "done": False}


def _done(
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict[str, Any]:
    return {
        "content": "",
        "done": True,
        "metadata": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": 1.0,
            "model": "test-model",
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
        },
    }


def _tool_call(name: str, arguments: str, call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _turns(*turns: list[dict[str, Any]]) -> MagicMock:
    """A stream_complete mock that returns one async iterator per call (turn)."""
    return MagicMock(side_effect=[_AsyncIter(t) for t in turns])


# ---------------------------------------------------------------------------
# Simple path: no tools → one streaming turn produces the answer
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamSimple:
    """No tool_calls on the first turn → that turn streams the answer directly."""

    async def test_simple_stream_yields_tokens_and_done(self) -> None:
        llm = AsyncMock()
        llm.chat = AsyncMock()
        llm.stream_complete = _turns(
            [
                _token("Hello"),
                _token(" world"),
                _done(finish_reason="stop", input_tokens=5, output_tokens=2),
            ]
        )
        registry = _make_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)
        config = _flex_config("simple-stream", tools_allowed=["search"])

        events: list[dict[str, Any]] = []
        async for ev in runner.run_flexible_stream(
            config, user_message="ping", session={}
        ):
            events.append(ev)

        tokens = [e for e in events if e["type"] == "token"]
        assert [t["delta"] for t in tokens] == ["Hello", " world"]
        assert events[-1]["type"] == "done"
        assert events[-1]["metadata"]["final_answer"] == "Hello world"
        # One streaming turn produces the answer — no separate decide-stop chat.
        llm.chat.assert_not_called()
        llm.stream_complete.assert_called_once()
        kwargs = llm.stream_complete.call_args.kwargs
        assert "messages" in kwargs and isinstance(kwargs["messages"], list)
        assert "tools" in kwargs and isinstance(kwargs["tools"], list)


# ---------------------------------------------------------------------------
# Tool-loop path: stream_complete(tool_calls) → search → stream_complete(answer)
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamWithSearchTool:
    """tool_calls path emits step + sources + tokens + done."""

    async def test_search_tool_emits_sources_and_streams(self) -> None:
        llm = AsyncMock()
        llm.chat = AsyncMock()
        llm.stream_complete = _turns(
            [
                _done(
                    tool_calls=[_tool_call("search", '{"q": "ai"}', "tc-001")],
                    finish_reason="tool_calls",
                    input_tokens=8,
                    output_tokens=2,
                )
            ],
            [
                _token("Based on"),
                _token(" results"),
                _done(finish_reason="stop"),
            ],
        )
        registry = _make_registry(
            "search",
            tool_results={
                "search": {
                    "response": {
                        "items": [
                            {"id": "c1", "title": "Doc 1", "url": "http://x/1"},
                            {"id": "c2", "title": "Doc 2", "url": "http://x/2"},
                        ]
                    }
                }
            },
        )
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)
        config = _flex_config("with-search", tools_allowed=["search"])

        events: list[dict[str, Any]] = []
        async for ev in runner.run_flexible_stream(
            config, user_message="find ai", session={}
        ):
            events.append(ev)

        types = [e["type"] for e in events]
        assert "sources" in types
        sources_ev = next(e for e in events if e["type"] == "sources")
        assert len(sources_ev["items"]) == 2
        assert sources_ev["items"][0]["title"] == "Doc 1"
        assert sources_ev["items"][0]["content_id"] == "c1"

        token_deltas = [e["delta"] for e in events if e["type"] == "token"]
        assert token_deltas == ["Based on", " results"]
        assert events[-1]["type"] == "done"
        assert events[-1]["metadata"]["final_answer"] == "Based on results"

        step_events = [e for e in events if e["type"] == "step"]
        assert any(
            s["action"] == "tool_call" and s["tool"] == "search" for s in step_events
        )
        # Two turns (tool decision + answer) — neither re-generates the other.
        assert llm.stream_complete.call_count == 2
        llm.chat.assert_not_called()


# ---------------------------------------------------------------------------
# Default system prompt: derived from the live tool registry (no config needed)
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamDefaultSystemPrompt:
    """No configured system_prompt → identity prompt rendered from templates."""

    async def test_default_system_prompt_has_identity_without_tool_list(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(*, messages: list[dict[str, Any]], **__: Any) -> _AsyncIter:
            captured["messages"] = messages
            return _AsyncIter([_token("hi"), _done(finish_reason="stop")])

        llm = AsyncMock()
        llm.chat = AsyncMock()
        llm.stream_complete = MagicMock(side_effect=_capture)
        registry = _make_registry("search", "get_content_detail")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)
        config = _flex_config(
            "default-prompt", tools_allowed=["search", "get_content_detail"]
        )

        async for _ in runner.run_flexible_stream(
            config, user_message="你是谁", session={}
        ):
            pass

        system_msg = captured["messages"][0]
        assert system_msg["role"] == "system"
        text = system_msg["content"]
        assert "IntelliSource" in text
        assert "get_content_detail" not in text, (
            "tool list must not be rendered into the system prompt; tools reach "
            "the model via the tools= param"
        )

    async def test_configured_system_prompt_takes_precedence(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(*, messages: list[dict[str, Any]], **__: Any) -> _AsyncIter:
            captured["messages"] = messages
            return _AsyncIter([_done(finish_reason="stop")])

        llm = AsyncMock()
        llm.chat = AsyncMock()
        llm.stream_complete = MagicMock(side_effect=_capture)
        registry = _make_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)
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

        async for _ in runner.run_flexible_stream(
            config, user_message="hi", session={}
        ):
            pass

        assert captured["messages"][0]["content"] == "CUSTOM-PROMPT-SENTINEL"


# ---------------------------------------------------------------------------
# Tool-borne answer: model answers via summarize_for_user, streams no free text
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamToolBorneAnswer:
    """When the terminal turn streams nothing, surface the tool-borne answer."""

    async def test_summarize_tool_answer_emitted_when_stream_empty(self) -> None:
        llm = AsyncMock()
        llm.chat = AsyncMock()
        llm.stream_complete = _turns(
            [
                _done(
                    tool_calls=[
                        _tool_call("summarize_for_user", '{"content": "raw"}', "tc-sum")
                    ],
                    finish_reason="tool_calls",
                    input_tokens=4,
                    output_tokens=1,
                )
            ],
            # terminal turn streams no content (model treats the tool as the answer)
            [_done(finish_reason="stop")],
        )
        registry = _make_registry(
            "summarize_for_user",
            tool_results={
                "summarize_for_user": {
                    "status": "ok",
                    "tool": "summarize_for_user",
                    "summary": "这是基于知识库的总结答案。",
                }
            },
        )
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)
        config = _flex_config("tool-answer", tools_allowed=["summarize_for_user"])

        events: list[dict[str, Any]] = []
        async for ev in runner.run_flexible_stream(
            config, user_message="总结", session={}
        ):
            events.append(ev)

        token_deltas = [e["delta"] for e in events if e["type"] == "token"]
        assert token_deltas == ["这是基于知识库的总结答案。"]
        assert events[-1]["type"] == "done"
        assert events[-1]["metadata"]["final_answer"] == "这是基于知识库的总结答案。"


# ---------------------------------------------------------------------------
# Budget exhaustion: skip the LLM call, done carries budget_exhausted
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamBudget:
    """Budget=0 short-circuits before any LLM call."""

    async def test_zero_budget_emits_done_only(self) -> None:
        llm = AsyncMock()
        llm.chat = AsyncMock()
        llm.stream_complete = MagicMock()
        registry = _make_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)
        config = _flex_config("budget-zero", tools_allowed=["search"])

        events: list[dict[str, Any]] = []
        async for ev in runner.run_flexible_stream(
            config, user_message="hi", session={}, max_tokens_budget=0
        ):
            events.append(ev)

        assert len(events) == 1
        assert events[0]["type"] == "done"
        assert events[0]["metadata"].get("budget_exhausted") is True
        llm.chat.assert_not_called()
        llm.stream_complete.assert_not_called()


# ---------------------------------------------------------------------------
# streaming turn failure → error event
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamError:
    """A streaming turn raising → emits {type: error, detail: ...}."""

    async def test_stream_failure_emits_error(self) -> None:
        async def _boom_iter() -> Any:
            raise RuntimeError("upstream blew up")
            yield  # pragma: no cover

        llm = AsyncMock()
        llm.chat = AsyncMock()
        llm.stream_complete = MagicMock(return_value=_boom_iter())
        registry = _make_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)
        config = _flex_config("stream-fail", tools_allowed=["search"])

        events: list[dict[str, Any]] = []
        async for ev in runner.run_flexible_stream(
            config, user_message="x", session={}
        ):
            events.append(ev)

        assert events[-1]["type"] == "error"
        assert "upstream blew up" in events[-1]["detail"]


# ---------------------------------------------------------------------------
# preview agent mode rejected
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamPreviewRejected:
    """preview agent_mode is not a stream concept; explicitly reject."""

    async def test_preview_mode_raises(self) -> None:
        llm = AsyncMock()
        registry = _make_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm)
        config = _flex_config(
            "preview-rej", tools_allowed=["search"], agent_mode="preview"
        )

        with pytest.raises(IntelliSourceError):
            async for _ev in runner.run_flexible_stream(
                config, user_message="x", session={}
            ):
                pass
