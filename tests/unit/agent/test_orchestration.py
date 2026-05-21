"""Agent orchestration integration tests.

Covers:
- AC-T056-1: 6 processing workflows via Agent orchestration
- AC-T056-2: flexible mode: Agent calls atomic tools + llm_complete
- AC-T056-3: strict mode: only atomic tools, zero LLM calls
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.runner import AgentRunner
from intellisource.agent.tools import AgentToolRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def full_registry() -> AgentToolRegistry:
    """Registry with defaults + atomic tools."""
    reg = AgentToolRegistry()
    reg.register_defaults()
    reg.register_atomic_tools()
    return reg


def _make_llm_gateway(
    tool_calls_sequence: list[list[dict[str, Any]]],
) -> AsyncMock:
    """Build a mock LLM gateway that returns tool calls in sequence."""
    gw = AsyncMock()
    call_idx = 0

    async def _chat(**kwargs: Any) -> dict[str, Any]:
        nonlocal call_idx
        if call_idx < len(tool_calls_sequence):
            tcs = tool_calls_sequence[call_idx]
            call_idx += 1
            return {
                "tool_calls": tcs,
                "content": "",
                "done": len(tcs) == 0,
                "usage": {"total_tokens": 100},
            }
        return {
            "tool_calls": [],
            "content": "done",
            "done": True,
            "usage": {"total_tokens": 0},
        }

    gw.chat.side_effect = _chat
    return gw


# ===================================================================
# AC-T056-1: Extract workflow via Agent
# ===================================================================


class TestExtractWorkflow:
    """Extract workflow through Agent orchestration."""

    async def test_extract_via_atomic_tool(
        self, full_registry: AgentToolRegistry
    ) -> None:
        """AC-T056-1: Agent invokes regex_extract for extraction."""
        gw = _make_llm_gateway(
            [
                [
                    {
                        "name": "regex_extract",
                        "arguments": {
                            "body_text": "Title: Test Article\nDate: 2026-01-01"
                        },
                        "id": "tc-1",
                    }
                ],
                [],  # done
            ]
        )
        runner = AgentRunner(tool_registry=full_registry, llm_gateway=gw)
        config = PipelineConfig.from_dict(
            {
                "name": "extract-test",
                "mode": "flexible",
                "tools_allowed": ["regex_extract", "llm_complete"],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )
        result = await runner.run_flexible(
            config, user_message="extract fields", session={}
        )
        assert result["status"] == "success"
        assert result["steps_executed"] >= 2


# ===================================================================
# AC-T056-1: Dedup workflow
# ===================================================================


class TestDedupWorkflow:
    """Dedup workflow through Agent orchestration."""

    async def test_dedup_via_atomic_tools(
        self, full_registry: AgentToolRegistry
    ) -> None:
        """AC-T056-1: Agent invokes fingerprint_dedup for dedup check."""
        gw = _make_llm_gateway(
            [
                [
                    {
                        "name": "fingerprint_dedup",
                        "arguments": {
                            "title": "Test",
                            "body_text": "Content",
                            "known_fingerprints": [],
                        },
                        "id": "tc-1",
                    }
                ],
                [],
            ]
        )
        runner = AgentRunner(tool_registry=full_registry, llm_gateway=gw)
        config = PipelineConfig.from_dict(
            {
                "name": "dedup-test",
                "mode": "flexible",
                "tools_allowed": ["fingerprint_dedup", "fingerprint_generate"],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )
        result = await runner.run_flexible(config, user_message="check dup", session={})
        assert result["status"] == "success"


# ===================================================================
# AC-T056-1: Cluster workflow
# ===================================================================


class TestClusterWorkflow:
    """Cluster workflow through Agent orchestration."""

    async def test_cluster_via_tfidf(self, full_registry: AgentToolRegistry) -> None:
        """AC-T056-1: Agent invokes tfidf_keywords for clustering."""
        gw = _make_llm_gateway(
            [
                [
                    {
                        "name": "tfidf_keywords",
                        "arguments": {
                            "title": "AI News",
                            "body_text": "Machine learning advances",
                        },
                        "id": "tc-1",
                    }
                ],
                [],
            ]
        )
        runner = AgentRunner(tool_registry=full_registry, llm_gateway=gw)
        config = PipelineConfig.from_dict(
            {
                "name": "cluster-test",
                "mode": "flexible",
                "tools_allowed": ["tfidf_keywords", "find_nearest_cluster"],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )
        result = await runner.run_flexible(
            config, user_message="cluster content", session={}
        )
        assert result["status"] == "success"


# ===================================================================
# AC-T056-1: Summarize workflow
# ===================================================================


class TestSummarizeWorkflow:
    """Summarize workflow through Agent orchestration."""

    async def test_summarize_via_atomic_tool(
        self, full_registry: AgentToolRegistry
    ) -> None:
        """AC-T056-1: Agent invokes truncate_summary."""
        gw = _make_llm_gateway(
            [
                [
                    {
                        "name": "truncate_summary",
                        "arguments": {
                            "cluster_contents": [
                                {
                                    "title": "Article 1",
                                    "body_text": "First. Second. Third.",
                                }
                            ]
                        },
                        "id": "tc-1",
                    }
                ],
                [],
            ]
        )
        runner = AgentRunner(tool_registry=full_registry, llm_gateway=gw)
        config = PipelineConfig.from_dict(
            {
                "name": "summarize-test",
                "mode": "flexible",
                "tools_allowed": ["truncate_summary", "llm_complete"],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )
        result = await runner.run_flexible(config, user_message="summarize", session={})
        assert result["status"] == "success"


# ===================================================================
# AC-T056-1: Tag workflow
# ===================================================================


class TestTagWorkflow:
    """Tag workflow through Agent orchestration."""

    async def test_tag_via_atomic_tool(self, full_registry: AgentToolRegistry) -> None:
        """AC-T056-1: Agent invokes keyword_tag."""
        gw = _make_llm_gateway(
            [
                [
                    {
                        "name": "keyword_tag",
                        "arguments": {
                            "body_text": "Python machine learning tutorial",
                            "title": "ML Guide",
                            "tag_library": ["Python", "ML", "AI", "Java"],
                        },
                        "id": "tc-1",
                    }
                ],
                [],
            ]
        )
        runner = AgentRunner(tool_registry=full_registry, llm_gateway=gw)
        config = PipelineConfig.from_dict(
            {
                "name": "tag-test",
                "mode": "flexible",
                "tools_allowed": ["keyword_tag", "llm_complete"],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )
        result = await runner.run_flexible(
            config, user_message="tag content", session={}
        )
        assert result["status"] == "success"


# ===================================================================
# AC-T056-1: Push optimize workflow
# ===================================================================


class TestPushOptimizeWorkflow:
    """Push optimize workflow through Agent orchestration."""

    async def test_push_optimize_via_atomic_tool(
        self, full_registry: AgentToolRegistry
    ) -> None:
        """AC-T056-1: Agent invokes truncate_for_push."""
        gw = _make_llm_gateway(
            [
                [
                    {
                        "name": "truncate_for_push",
                        "arguments": {
                            "title": "A long article title needing truncation for push",
                            "body_text": "Detailed content. Multiple sentences here.",
                        },
                        "id": "tc-1",
                    }
                ],
                [],
            ]
        )
        runner = AgentRunner(tool_registry=full_registry, llm_gateway=gw)
        config = PipelineConfig.from_dict(
            {
                "name": "push-opt-test",
                "mode": "flexible",
                "tools_allowed": [
                    "truncate_for_push",
                    "filter_sensitive",
                    "llm_complete",
                ],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )
        result = await runner.run_flexible(
            config, user_message="optimize push", session={}
        )
        assert result["status"] == "success"


# ===================================================================
# AC-T056-2: Flexible mode uses atomic + llm_complete
# ===================================================================


class TestFlexibleModeToolMix:
    """AC-T056-2: flexible mode calls both atomic and llm_complete tools."""

    async def test_mixed_tool_calls(self, full_registry: AgentToolRegistry) -> None:
        """AC-T056-2: Agent calls regex_extract then llm_complete."""
        gw = _make_llm_gateway(
            [
                [
                    {
                        "name": "regex_extract",
                        "arguments": {"body_text": "Title: Test\nAuthors: Alice, Bob"},
                        "id": "tc-1",
                    }
                ],
                [
                    {
                        "name": "llm_complete",
                        "arguments": {
                            "call_type": "extract",
                            "prompt_vars": {"text": "more data"},
                        },
                        "id": "tc-2",
                    }
                ],
                [],
            ]
        )
        runner = AgentRunner(tool_registry=full_registry, llm_gateway=gw)
        config = PipelineConfig.from_dict(
            {
                "name": "mixed-test",
                "mode": "flexible",
                "tools_allowed": ["regex_extract", "llm_complete"],
                "steps": [],
                "max_steps": 10,
                "on_failure": "skip",
            }
        )
        result = await runner.run_flexible(
            config, user_message="extract all", session={}
        )
        assert result["status"] == "success"
        assert result["steps_executed"] == 3
        # Verify tool results were serialized back into messages
        calls = gw.chat.call_args_list
        second_call_msgs = calls[1].kwargs.get("messages") or calls[1].args[0]
        tool_msgs = [m for m in second_call_msgs if m["role"] == "tool"]
        assert len(tool_msgs) >= 1
        # Verify the tool result is valid JSON
        parsed = json.loads(tool_msgs[0]["content"])
        assert "title" in parsed  # regex_extract returns title field


# ===================================================================
# AC-T056-3: Strict mode - only atomic tools, zero LLM
# ===================================================================


class TestStrictModeNoLLM:
    """AC-T056-3: strict mode uses only atomic tools, no LLM calls."""

    async def test_strict_no_llm_calls(self, full_registry: AgentToolRegistry) -> None:
        """AC-T056-3: strict pipeline runs without LLM gateway."""
        # No LLM gateway needed for strict mode
        runner = AgentRunner(tool_registry=full_registry, llm_gateway=None)
        config = PipelineConfig.from_dict(
            {
                "name": "strict-atomic-test",
                "mode": "strict",
                "tools_allowed": [
                    "regex_extract",
                    "fingerprint_generate",
                    "keyword_tag",
                ],
                "steps": [
                    {
                        "tool": "regex_extract",
                        "params": {"body_text": "Title: News\nDate: 2026-01-01"},
                    },
                    {
                        "tool": "fingerprint_generate",
                        "params": {"title": "News", "body_text": "content"},
                    },
                    {
                        "tool": "keyword_tag",
                        "params": {
                            "body_text": "Python tutorial",
                            "title": "Learn",
                            "tag_library": ["Python", "Java"],
                        },
                    },
                ],
                "max_steps": 10,
                "on_failure": "abort",
            }
        )
        result = await runner.run_strict(config, params={})
        assert result["status"] == "success"
        assert result["steps_executed"] == 3
        # Verify all 3 tool results are present
        assert len(result["results"]) == 3
        # regex_extract result
        extract_out = result["results"][0]["output"]
        assert "title" in extract_out
        # fingerprint_generate result
        fp_out = result["results"][1]["output"]
        assert len(fp_out) == 64  # SHA-256 hex
        # keyword_tag result
        tag_out = result["results"][2]["output"]
        assert isinstance(tag_out, list)
