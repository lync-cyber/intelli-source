"""Tests for AgentRunner.run_flexible_stream() — RAG-aware SSE streaming.

Covers B-001 acceptance:
  - simple-no-tools path: single chat() → stream_complete → token events
  - with-tools path: chat → tool_call → chat → stream_complete; emits step
    events and (when search returns items) a sources event
  - budget exhaustion path: stream_complete is skipped; done carries
    budget_exhausted=True
  - stream_complete failure path: yields {"type": "error", ...}
  - preview agent mode: explicitly rejected by run_stream
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.agent.runner import AgentRunner
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.core.errors import IntelliSourceError
from intellisource.llm.gateway import LLMResult

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


def _stream_chunk(
    content: str = "", done: bool = False, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    ev: dict[str, Any] = {"content": content, "done": done}
    if done and metadata is not None:
        ev["metadata"] = metadata
    return ev


# ---------------------------------------------------------------------------
# Simple path: no tools → stream_complete only
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamSimple:
    """No tool_calls on first chat → straight into stream_complete."""

    async def test_simple_stream_yields_tokens_and_done(self) -> None:
        llm = AsyncMock()
        llm.chat = AsyncMock(
            return_value=LLMResult(
                content="ignored — stream rewrites",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )
        )
        llm.stream_complete = MagicMock(
            return_value=_AsyncIter(
                [
                    _stream_chunk("Hello", done=False),
                    _stream_chunk(" world", done=False),
                    _stream_chunk(
                        done=True, metadata={"input_tokens": 5, "output_tokens": 2}
                    ),
                ]
            )
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
        # chat must be called once for the decide-stop hop; stream_complete once
        llm.chat.assert_awaited_once()
        llm.stream_complete.assert_called_once()
        kwargs = llm.stream_complete.call_args.kwargs
        assert "messages" in kwargs and isinstance(kwargs["messages"], list)


# ---------------------------------------------------------------------------
# Tool-loop path: chat → tool_call(search) → chat(stop) → stream_complete
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamWithSearchTool:
    """tool_calls path emits step + sources + tokens + done in order."""

    async def test_search_tool_emits_sources_and_streams(self) -> None:
        call_count = 0

        async def _chat(**_: Any) -> LLMResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                tc = MagicMock()
                tc.function.name = "search"
                tc.function.arguments = '{"q": "ai"}'
                tc.id = "tc-001"
                return LLMResult(
                    content="",
                    metadata={
                        "tool_calls": [tc],
                        "finish_reason": "tool_calls",
                        "usage": {"total_tokens": 10},
                    },
                )
            return LLMResult(
                content="ignored",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=_chat)
        llm.stream_complete = MagicMock(
            return_value=_AsyncIter(
                [
                    _stream_chunk("Based on", done=False),
                    _stream_chunk(" results", done=False),
                    _stream_chunk(done=True, metadata={}),
                ]
            )
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

        step_events = [e for e in events if e["type"] == "step"]
        assert any(
            s["action"] == "tool_call" and s["tool"] == "search" for s in step_events
        )


# ---------------------------------------------------------------------------
# Default system prompt: derived from the live tool registry (no config needed)
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamDefaultSystemPrompt:
    """No configured system_prompt → identity+tools prompt rendered from templates."""

    async def test_default_system_prompt_lists_tools(self) -> None:
        captured: dict[str, Any] = {}

        async def _chat(*, messages: list[dict[str, Any]], **_: Any) -> LLMResult:
            captured["messages"] = messages
            return LLMResult(
                content="",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=_chat)
        llm.stream_complete = MagicMock(
            return_value=_AsyncIter(
                [_stream_chunk("hi", done=False), _stream_chunk(done=True, metadata={})]
            )
        )
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
        assert "search" in text and "get_content_detail" in text

    async def test_configured_system_prompt_takes_precedence(self) -> None:
        captured: dict[str, Any] = {}

        async def _chat(*, messages: list[dict[str, Any]], **_: Any) -> LLMResult:
            captured["messages"] = messages
            return LLMResult(
                content="",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=_chat)
        llm.stream_complete = MagicMock(
            return_value=_AsyncIter([_stream_chunk(done=True, metadata={})])
        )
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
    """When stream_complete yields nothing, surface the tool-borne answer."""

    async def test_summarize_tool_answer_emitted_when_stream_empty(self) -> None:
        call_count = 0

        async def _chat(**_: Any) -> LLMResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                tc = MagicMock()
                tc.function.name = "summarize_for_user"
                tc.function.arguments = '{"content": "raw"}'
                tc.id = "tc-sum"
                return LLMResult(
                    content="",
                    metadata={
                        "tool_calls": [tc],
                        "finish_reason": "tool_calls",
                        "usage": {"total_tokens": 5},
                    },
                )
            return LLMResult(
                content="",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=_chat)
        # stream_complete produces no content deltas (model considers the tool the
        # answer), so the loop would otherwise yield an empty reply.
        llm.stream_complete = MagicMock(
            return_value=_AsyncIter([_stream_chunk(done=True, metadata={})])
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
# Budget exhaustion: skip stream, done carries budget_exhausted
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamBudget:
    """Budget=0 short-circuits before any chat / stream_complete."""

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
# stream_complete failure → error event
# ---------------------------------------------------------------------------


class TestRunFlexibleStreamError:
    """stream_complete raising → emits {type: error, detail: ...}."""

    async def test_stream_complete_failure_emits_error(self) -> None:
        llm = AsyncMock()
        llm.chat = AsyncMock(
            return_value=LLMResult(
                content="",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )
        )

        async def _boom_iter() -> Any:
            raise RuntimeError("upstream blew up")
            yield  # pragma: no cover

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
