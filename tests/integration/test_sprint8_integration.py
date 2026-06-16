"""Sprint-8 integration tests (T-071).

Covers AC-T071-1 through AC-T071-9 with cross-module paths.
AC-T071-4 (circuit-breaker) is already covered in test_sprint7_integration.py.
AC-T071-10/11 (full pytest + mypy) are verified by orchestrator at close-out.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===========================================================================
# AC-T071-1: analyze mode + permission level (auto/confirm) combined
# ===========================================================================


def _flexible_config_with_mode_and_perms(
    name: str,
    agent_mode: str,
    tool_permissions: dict[str, str],
) -> Any:
    from intellisource.config.pipeline_models import PipelineConfig

    return PipelineConfig.from_dict(
        {
            "name": name,
            "mode": "flexible",
            "tools_allowed": ["search", "distribute", "process"],
            "tools_denied": [],
            "steps": [],
            "max_steps": 2,
            "on_failure": "skip",
            "agent_mode": agent_mode,
            "tool_permissions": tool_permissions,
        }
    )


def _make_registry_with(*tool_names: str) -> Any:
    from intellisource.agent.tools import AgentToolRegistry, PermissionLevel

    registry = AgentToolRegistry()
    for tname in tool_names:
        registry.register(
            name=tname,
            description=tname,
            parameters={},
            execute_fn=AsyncMock(return_value={"result": tname}),
            permission_level=PermissionLevel.auto,
        )
    return registry


def _make_tool_call_response(tool_name: str, tool_call_id: str) -> Any:
    from intellisource.llm.gateway import LLMResult

    tc = MagicMock()
    tc.id = tool_call_id
    tc.function = MagicMock()
    tc.function.name = tool_name
    tc.function.arguments = "{}"
    return LLMResult(
        content="",
        metadata={
            "tool_calls": [tc],
            "finish_reason": "tool_calls",
            "usage": {"total_tokens": 10, "prompt_tokens": 8, "completion_tokens": 2},
            "model": "gpt-4o-mini",
        },
    )


def _make_stop_response() -> Any:
    from intellisource.llm.gateway import LLMResult

    return LLMResult(
        content="done",
        metadata={
            "finish_reason": "stop",
            "usage": {"total_tokens": 5, "prompt_tokens": 4, "completion_tokens": 1},
            "model": "gpt-4o-mini",
        },
    )


class TestAnalyzeModeWithPermissions:
    """AC-T071-1: analyze mode blocks distribute/process; auto tool executes."""

    @pytest.mark.asyncio
    async def test_analyze_mode_blocks_distribute_allows_search(self) -> None:
        from intellisource.agent.runner import AgentRunner

        registry = _make_registry_with("search", "distribute")
        mock_gw = AsyncMock()

        # LLM first asks to call distribute (should be blocked by analyze),
        # then search (should execute), then stop.
        mock_gw.chat = AsyncMock(
            side_effect=[
                _make_tool_call_response("distribute", "tc-dist-1"),
                _make_tool_call_response("search", "tc-search-1"),
                _make_stop_response(),
            ]
        )

        config = _flexible_config_with_mode_and_perms(
            "test_analyze", "analyze", {"search": "auto"}
        )
        runner = AgentRunner(tool_registry=registry, llm_gateway=mock_gw)
        result = await runner.run_flexible(
            config, user_message="analyze please", session={}
        )

        # Find tool_results from the run
        all_results: list[dict[str, Any]] = result.get("results", [])

        distribute_entries = [r for r in all_results if r.get("tool") == "distribute"]
        search_entries = [r for r in all_results if r.get("tool") == "search"]

        assert len(distribute_entries) >= 1, "distribute should appear in tool_results"
        assert distribute_entries[0].get("denied") is True, (
            "distribute must be denied in analyze mode"
        )
        assert distribute_entries[0].get("reason") == "analyze_mode"

        assert len(search_entries) >= 1, "search should appear in tool_results"
        assert search_entries[0].get("denied") is not True, (
            "search must not be denied (auto permission, not in analyze-denied set)"
        )


# ===========================================================================
# AC-T071-2: auto_discover respects manual registration precedence
# ===========================================================================


class TestAutoDiscoverManualPrecedence:
    """AC-T071-2: hand-registered tool wins over discovered plugin with same name."""

    def test_manual_registration_not_overwritten_by_auto_discover(
        self, tmp_path: Path
    ) -> None:
        from intellisource.agent.tools import AgentToolRegistry, PermissionLevel

        registry = AgentToolRegistry()

        original_fn: Any = AsyncMock(return_value={"source": "manual"})
        registry.register(
            name="my_tool",
            description="manual",
            parameters={},
            execute_fn=original_fn,
            permission_level=PermissionLevel.auto,
        )

        # Write a plugin that also exports TOOL_DEFINITION for "my_tool"
        plugin_code = textwrap.dedent(
            """
            from intellisource.agent.tools import ToolDefinition, PermissionLevel
            from unittest.mock import AsyncMock

            TOOL_DEFINITION = ToolDefinition(
                name="my_tool",
                description="plugin version",
                parameters={},
                execute=AsyncMock(return_value={"source": "plugin"}),
                permission_level=PermissionLevel.auto,
            )
            """
        )
        (tmp_path / "my_tool_plugin.py").write_text(plugin_code, encoding="utf-8")

        # Write a second plugin with a unique name — should be registered
        unique_plugin_code = textwrap.dedent(
            """
            from intellisource.agent.tools import ToolDefinition, PermissionLevel
            from unittest.mock import AsyncMock

            TOOL_DEFINITION = ToolDefinition(
                name="unique_discovered_tool",
                description="only from plugin",
                parameters={},
                execute=AsyncMock(return_value={"source": "plugin"}),
                permission_level=PermissionLevel.auto,
            )
            """
        )
        (tmp_path / "unique_discovered_tool.py").write_text(
            unique_plugin_code, encoding="utf-8"
        )

        registry.auto_discover(tools_dir=tmp_path)

        # Manual registration preserved
        existing = registry.get("my_tool")
        assert existing is not None
        assert existing.execute is original_fn, (
            "manual execute_fn must not be replaced by auto_discover"
        )

        # Unique plugin registered
        discovered = registry.get("unique_discovered_tool")
        assert discovered is not None, "unique discovered tool should be registered"
        assert discovered.name == "unique_discovered_tool"


# ===========================================================================
# AC-T071-3: pipeline events recorded in flexible mode
# ===========================================================================


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestPipelineEventsInFlexibleMode:
    """AC-T071-3: 4+ event types written during a normal flexible run."""

    @pytest.mark.asyncio
    async def test_events_written_for_tool_call_cycle(self, tmp_path: Path) -> None:
        from intellisource.agent.events import PipelineEventLogger
        from intellisource.agent.runner import AgentRunner
        from intellisource.config.pipeline_models import PipelineConfig

        event_path = tmp_path / "events.jsonl"
        logger = PipelineEventLogger(event_path)

        registry = _make_registry_with("search")
        mock_gw = AsyncMock()
        mock_gw.chat = AsyncMock(
            side_effect=[
                _make_tool_call_response("search", "tc-s-1"),
                _make_stop_response(),
            ]
        )

        config = PipelineConfig.from_dict(
            {
                "name": "evt_test",
                "mode": "flexible",
                "tools_allowed": ["search"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )

        runner = AgentRunner(
            tool_registry=registry, llm_gateway=mock_gw, event_logger=logger
        )
        await runner.run_flexible(config, user_message="go", session={})

        records = _read_jsonl(event_path)
        event_types = [r["event"] for r in records]

        assert "pipeline_start" in event_types, "pipeline_start must be logged"
        assert "llm_call" in event_types, "llm_call must be logged"
        assert "tool_call" in event_types, "tool_call must be logged"
        assert "pipeline_complete" in event_types, "pipeline_complete must be logged"

        for record in records:
            assert "ts" in record
            assert "pipeline_name" in record
            assert "task_chain_id" in record

    @pytest.mark.asyncio
    async def test_pipeline_error_event_written_via_logger(
        self, tmp_path: Path
    ) -> None:
        from intellisource.agent.events import PipelineEventLogger

        event_path = tmp_path / "events_err.jsonl"
        logger = PipelineEventLogger(event_path)

        # Directly verify pipeline_error is written by PipelineEventLogger
        await logger.pipeline_error(
            pipeline_name="err_test",
            task_chain_id="chain-abc",
            error="simulated failure",
        )

        records = _read_jsonl(event_path)
        assert len(records) == 1
        assert records[0]["event"] == "pipeline_error"
        assert records[0]["pipeline_name"] == "err_test"
        assert records[0]["detail"]["error"] == "simulated failure"


# ===========================================================================
# AC-T071-5: SSE stream_complete end-to-end with token metadata
# ===========================================================================


class TestStreamCompleteIntegration:
    """AC-T071-5: stream_complete yields content chunks + final done event."""

    @pytest.mark.asyncio
    async def test_stream_complete_yields_chunks_and_metadata(self) -> None:
        from intellisource.llm.gateway import LLMGateway

        chunks_data = [
            ("Hello", None),
            (" world", None),
            ("!", None),
        ]

        def _make_chunk(content: str, usage: Any) -> MagicMock:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = content
            chunk.usage = usage
            chunk.model = "gpt-4o-mini"
            return chunk

        usage_mock = MagicMock()
        usage_mock.prompt_tokens = 15
        usage_mock.completion_tokens = 7

        raw_chunks = [_make_chunk(c, None) for c, _ in chunks_data]
        # Attach usage to last content chunk
        raw_chunks[-1].usage = usage_mock

        async def _aiter_chunks() -> AsyncIterator[Any]:
            for chunk in raw_chunks:
                yield chunk

        async def _fake_acompletion_stream(**kwargs: Any) -> AsyncIterator[Any]:
            return _aiter_chunks()

        target = "intellisource.llm.gateway.litellm.acompletion"
        with patch(target, _fake_acompletion_stream):
            gw = LLMGateway()
            collected: list[dict[str, Any]] = []
            async for event in gw.stream_complete("hello", model="gpt-4o-mini"):
                collected.append(event)

        content_events = [e for e in collected if not e.get("done", False)]
        done_events = [e for e in collected if e.get("done") is True]

        n_content = len(content_events)
        assert n_content == 3, f"expected 3 content chunks, got {n_content}"
        assert all(e.get("content") for e in content_events), (
            "each content event must carry text"
        )

        assert len(done_events) == 1, "exactly one done=True event expected"
        meta = done_events[0]["metadata"]
        assert "input_tokens" in meta, "metadata must include input_tokens"
        assert "output_tokens" in meta, "metadata must include output_tokens"
        assert meta["input_tokens"] == 15
        assert meta["output_tokens"] == 7


# ===========================================================================
# AC-T071-6/7/8: smoke import-chain validation
# ===========================================================================


class TestSmokeImportChain:
    """AC-T071-6/7/8: import chain for composition, system router, and celery_app."""

    def test_composition_symbols_importable(self) -> None:
        from intellisource.composition import (  # noqa: F401
            _build_deps_bundle,
            _install_agent_runner,
        )

    def test_system_router_importable(self) -> None:
        from fastapi import APIRouter

        from intellisource.api.routers.system import router

        assert isinstance(router, APIRouter)
        assert len(router.routes) > 0

    def test_celery_app_importable(self) -> None:
        from celery import Celery

        from intellisource.scheduler.celery_app import celery_app

        assert isinstance(celery_app, Celery)


# ===========================================================================
# AC-T071-9: chat_session vs agent flexible compaction consistency (T-079)
# ===========================================================================


class TestCompactionConsistency:
    """AC-T071-9: compact_messages_for_chat and compact_messages share same pipeline."""

    @pytest.mark.asyncio
    async def test_both_paths_keep_same_head_and_tail(self) -> None:
        from intellisource.llm.compaction import (
            _chat_compaction_context_window,
            compact_messages,
            compact_messages_for_chat,
        )
        from intellisource.llm.model_config import ModelProfile

        # Build 20 messages: alternating user/assistant.
        # Each content is 80 chars; estimate_tokens = 80//4+1 = 21.
        # Total = 20*21 = 420. max_tokens = 100 → threshold = min(200*0.8, 100) = 100.
        # 420 > 100 → compaction triggers.
        messages: list[dict[str, Any]] = []
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append({"role": role, "content": f"msg-{i:02d} " + "x" * 76})

        max_tokens = 100

        # Gateway mock: estimate_tokens counts chars//4; complete returns summary.
        # patch _build_summary_prompt to avoid missing template file on disk.
        mock_gw = MagicMock()
        mock_gw.estimate_tokens = MagicMock(
            side_effect=lambda text, model="gpt-4o-mini": len(text) // 4 + 1
        )
        summary_result = MagicMock()
        summary_result.content = "summarized"
        mock_gw.complete = AsyncMock(return_value=summary_result)

        with patch(
            "intellisource.llm.compaction._build_summary_prompt",
            return_value="summarize this",
        ):
            # Path A: compact_messages_for_chat
            result_a = await compact_messages_for_chat(
                list(messages), gateway=mock_gw, max_tokens=max_tokens
            )

            # Path B: compact_messages with equivalent ModelProfile
            profile = ModelProfile(
                temperature=0.0,
                max_tokens=max_tokens,
                context_window=_chat_compaction_context_window(max_tokens),
            )
            result_b = await compact_messages(
                list(messages),
                gateway=mock_gw,
                profile=profile,
                context_token_budget=max_tokens,
            )

        # Both should produce a non-empty result
        assert len(result_a) > 0, "compact_messages_for_chat must return non-empty"
        assert len(result_b) > 0, "compact_messages must return non-empty"

        # Both start with a system summary (LLM succeeded)
        assert result_a[0]["role"] == "system", "Path A head must be system summary"
        assert result_b[0]["role"] == "system", "Path B head must be system summary"

        # Tail alignment: both should keep the same most-recent messages
        tail_a = [m["content"] for m in result_a[1:]]
        tail_b = [m["content"] for m in result_b[1:]]
        assert tail_a == tail_b, "both compact paths must retain the same recent tail"


# ===========================================================================
# AC-T071-5 (SR-005): SSE end-to-end via FastAPI ASGI client
# ===========================================================================


class TestSSEAsgiEndToEnd:
    """SR-005 superseded by B-001.

    The original test mocked ``litellm.acompletion`` and asserted the legacy
    SSE shape (``{content, done}``). B-001 routed ``/search/chat/stream``
    through ``AgentRunner.run_flexible_stream`` and changed the SSE event
    contract to ``{type: step|sources|token|done|error, ...}``. End-to-end
    coverage now lives in
    ``tests/integration/test_search_chat_stream_uses_rag.py``.
    """
