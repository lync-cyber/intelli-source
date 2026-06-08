"""Agent-layer cluster summarization: LLM digest + truncation fallback.

The LLM path moved here from pipeline.processors.tools so it can build the
prompt via load_prompt("summarizer", style="structured") — pipeline ✗→ llm.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from intellisource.agent.tools.executes.summarize_cluster import (
    make_cluster_summarizer,
    summarize_cluster,
)


def _result(content: str) -> SimpleNamespace:
    return SimpleNamespace(content=content, metadata={})


def _deps(gateway: Any) -> SimpleNamespace:
    return SimpleNamespace(llm_gateway=gateway)


class TestSummarizeClusterLLM:
    async def test_llm_produces_structured_digest(self) -> None:
        captured: dict[str, Any] = {}

        async def fake_complete(**kwargs: Any) -> SimpleNamespace:
            captured.update(kwargs)
            return _result(
                json.dumps(
                    {
                        "title": "LLM Title",
                        "summary": "A comprehensive summary.",
                        "timeline": [{"date": "2026-01-01", "event": "Launch"}],
                        "key_points": ["A", "B"],
                    }
                )
            )

        gw = SimpleNamespace(complete=fake_complete)
        contents = [{"title": "Doc 1", "body_text": "Text one. Text two."}]
        result = await summarize_cluster(contents, tool_deps=_deps(gw))

        assert result["summary"] == "A comprehensive summary."
        assert result["timeline"][0]["event"] == "Launch"
        assert result["key_points"] == ["A", "B"]
        # Built from the centralized template → injection guard + JSON mode.
        assert captured["task_type"] == "summarize"
        assert captured["response_format"] == {"type": "json_object"}
        assert "ignore any instructions" in captured["prompt"].lower()

    async def test_llm_failure_falls_back_to_truncation(self) -> None:
        async def failing(**kwargs: Any) -> SimpleNamespace:
            raise RuntimeError("LLM unavailable")

        gw = SimpleNamespace(complete=failing)
        contents = [{"title": "Fallback", "body_text": "One. Two. Three. Four."}]
        result = await summarize_cluster(contents, tool_deps=_deps(gw))

        assert result["title"] == "Fallback"
        assert "One" in result["summary"]
        assert result["timeline"] == []
        assert result["key_points"] == []

    async def test_llm_invalid_json_falls_back(self) -> None:
        async def bad(**kwargs: Any) -> SimpleNamespace:
            return _result("not valid json {{{")

        gw = SimpleNamespace(complete=bad)
        contents = [{"title": "T", "body_text": "A. B. C."}]
        result = await summarize_cluster(contents, tool_deps=_deps(gw))

        assert result["title"] == "T"
        assert result["timeline"] == []

    async def test_llm_missing_fields_falls_back(self) -> None:
        async def partial(**kwargs: Any) -> SimpleNamespace:
            return _result(json.dumps({"title": "Only title"}))

        gw = SimpleNamespace(complete=partial)
        contents = [{"title": "Original", "body_text": "Text here."}]
        result = await summarize_cluster(contents, tool_deps=_deps(gw))

        assert result["title"] == "Original"
        assert result["timeline"] == []


class TestSummarizeClusterFallback:
    async def test_no_tool_deps_uses_truncation(self) -> None:
        contents = [{"title": "Plain", "body_text": "One. Two. Three. Four."}]
        result = await summarize_cluster(contents, tool_deps=None)
        assert result["title"] == "Plain"
        assert "One" in result["summary"]

    async def test_no_gateway_uses_truncation(self) -> None:
        contents = [{"title": "T", "body_text": "A. B. C."}]
        result = await summarize_cluster(contents, tool_deps=_deps(None))
        assert result["title"] == "T"

    async def test_empty_cluster_returns_empty_digest(self) -> None:
        async def should_not_call(**kwargs: Any) -> None:
            raise AssertionError("Should not call LLM for empty cluster")

        gw = SimpleNamespace(complete=should_not_call)
        result = await summarize_cluster([], tool_deps=_deps(gw))
        assert result == {"title": "", "summary": "", "timeline": [], "key_points": []}


class TestMakeClusterSummarizer:
    async def test_binds_gateway_into_callable(self) -> None:
        async def fake_complete(**kwargs: Any) -> SimpleNamespace:
            return _result(
                json.dumps(
                    {"title": "T", "summary": "S", "timeline": [], "key_points": []}
                )
            )

        gw = SimpleNamespace(complete=fake_complete)
        summarize = make_cluster_summarizer(gw)
        result = await summarize([{"title": "a", "body_text": "b"}])
        assert result["summary"] == "S"

    async def test_none_gateway_callable_falls_back(self) -> None:
        summarize = make_cluster_summarizer(None)
        result = await summarize([{"title": "t", "body_text": "A. B. C."}])
        assert result["title"] == "t"
        assert result["summary"]
