"""Tests for AgentMode enumeration and mode-specific behavior in AgentRunner.

Covers AC-T064-1 through AC-T064-6:
- AgentMode enum defines process/analyze/preview
- PipelineConfig accepts optional agent_mode field (default process)
- analyze mode hard-blocks distribute and process tools
- preview mode dry-runs all tool calls and returns plan list
- process mode behavior is identical to existing flexible mode (backward compat)
- mypy --strict: verified by CI
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from intellisource.agent.runner import AgentMode, AgentRunner
from intellisource.agent.tool_gating import ToolPermissionResolver
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.llm.gateway import LLMResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_registry(*tool_names: str) -> MagicMock:
    registry = MagicMock()
    tool_map = {name: AsyncMock(return_value={"result": name}) for name in tool_names}

    def _get(name: str) -> AsyncMock | None:
        return tool_map.get(name)

    registry.get = MagicMock(side_effect=_get)
    registry.list_tools = MagicMock(return_value=list(tool_map.keys()))
    return registry


def _flexible_config(
    name: str,
    tools_allowed: list[str],
    max_steps: int = 5,
    agent_mode: str | None = None,
) -> PipelineConfig:
    data: dict = {
        "name": name,
        "mode": "flexible",
        "tools_allowed": tools_allowed,
        "tools_denied": [],
        "steps": [],
        "max_steps": max_steps,
        "on_failure": "skip",
    }
    if agent_mode is not None:
        data["agent_mode"] = agent_mode
    return PipelineConfig.from_dict(data)


def _one_shot_llm(tool_name: str | None = None) -> AsyncMock:
    """Return LLM mock that requests one tool call then stops."""
    call_count = 0
    llm_gw = AsyncMock()

    async def _chat(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1 and tool_name is not None:
            tc = MagicMock()
            tc.function.name = tool_name
            tc.function.arguments = "{}"
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
    return llm_gw


# ---------------------------------------------------------------------------
# AC-T064-1: AgentMode enum definition
# ---------------------------------------------------------------------------


class TestAgentModeEnum:
    """AC-T064-1: AgentMode defines exactly three modes."""

    def test_process_mode_value(self) -> None:
        """AgentMode.process has string value 'process'."""
        assert AgentMode.process.value == "process"

    def test_analyze_mode_value(self) -> None:
        """AgentMode.analyze has string value 'analyze'."""
        assert AgentMode.analyze.value == "analyze"

    def test_preview_mode_value(self) -> None:
        """AgentMode.preview has string value 'preview'."""
        assert AgentMode.preview.value == "preview"

    def test_enum_has_exactly_three_members(self) -> None:
        """AgentMode contains exactly process, analyze, preview."""
        values = {m.value for m in AgentMode}
        assert values == {"process", "analyze", "preview"}


# ---------------------------------------------------------------------------
# AC-T064-2: PipelineConfig agent_mode field
# ---------------------------------------------------------------------------


class TestPipelineConfigAgentMode:
    """AC-T064-2: PipelineConfig parses optional agent_mode field."""

    def test_agent_mode_defaults_to_process(self) -> None:
        """agent_mode defaults to 'process' when omitted from config dict."""
        config = PipelineConfig.from_dict(
            {
                "name": "no-mode",
                "mode": "flexible",
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )
        assert config.agent_mode == "process"

    def test_agent_mode_analyze_parsed(self) -> None:
        """agent_mode='analyze' is parsed and stored on PipelineConfig."""
        config = PipelineConfig.from_dict(
            {
                "name": "readonly-pipeline",
                "mode": "flexible",
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
                "agent_mode": "analyze",
            }
        )
        assert config.agent_mode == "analyze"

    def test_agent_mode_preview_parsed(self) -> None:
        """agent_mode='preview' is parsed and stored on PipelineConfig."""
        config = PipelineConfig.from_dict(
            {
                "name": "preview-pipeline",
                "mode": "flexible",
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
                "agent_mode": "preview",
            }
        )
        assert config.agent_mode == "preview"

    def test_agent_mode_process_explicit(self) -> None:
        """agent_mode='process' when explicitly set is stored correctly."""
        config = PipelineConfig.from_dict(
            {
                "name": "explicit-process",
                "mode": "flexible",
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
                "agent_mode": "process",
            }
        )
        assert config.agent_mode == "process"


# ---------------------------------------------------------------------------
# AC-T064-3: analyze mode denies distribute and process tools
# ---------------------------------------------------------------------------


class TestAnalyzeModeDeniedTools:
    """AC-T064-3: analyze mode hard-blocks distribute and process tools."""

    async def test_analyze_mode_blocks_distribute_even_if_allowed(self) -> None:
        """distribute is not executed even if in tools_allowed under analyze mode."""
        llm_gw = _one_shot_llm("distribute")
        registry = _make_tool_registry("distribute", "search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "analyze-deny-distribute",
            tools_allowed=["distribute", "search"],
            agent_mode="analyze",
        )

        result = await runner.run_flexible(config, user_message="hi", session={})

        distribute_mock = registry.get("distribute")
        assert distribute_mock is None or not distribute_mock.called
        assert result["status"] == "success"

    async def test_analyze_mode_blocks_process_even_if_allowed(self) -> None:
        """process is not executed even if in tools_allowed under analyze mode."""
        llm_gw = _one_shot_llm("process")
        registry = _make_tool_registry("process", "search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "analyze-deny-process",
            tools_allowed=["process", "search"],
            agent_mode="analyze",
        )

        result = await runner.run_flexible(config, user_message="hi", session={})

        process_mock = registry.get("process")
        assert process_mock is None or not process_mock.called
        assert result["status"] == "success"

    async def test_analyze_mode_allows_search_tool(self) -> None:
        """search tool is callable in analyze mode."""
        llm_gw = _one_shot_llm("search")
        registry = _make_tool_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "analyze-allow-search",
            tools_allowed=["search"],
            agent_mode="analyze",
        )

        result = await runner.run_flexible(config, user_message="hi", session={})

        search_mock = registry.get("search")
        assert search_mock is not None
        search_mock.assert_awaited_once()
        assert result["status"] == "success"

    async def test_analyze_mode_tool_descriptors_exclude_blocked_tools(self) -> None:
        """analyze mode strips distribute/process from the LLM tool descriptor list."""
        llm_gw = AsyncMock()
        llm_gw.chat.return_value = LLMResult(
            content="done",
            metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
        )
        registry = _make_tool_registry("distribute", "process", "search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "analyze-descriptors",
            tools_allowed=["distribute", "process", "search"],
            agent_mode="analyze",
        )

        await runner.run_flexible(config, user_message="analyze", session={})

        tools_passed = llm_gw.chat.await_args.kwargs["tools"]
        tool_names = [t["function"]["name"] for t in tools_passed]
        assert "distribute" not in tool_names
        assert "process" not in tool_names
        assert "search" in tool_names


# ---------------------------------------------------------------------------
# AC-T064-4: preview mode dry-runs all tools and returns plan
# ---------------------------------------------------------------------------


class TestPreviewMode:
    """AC-T064-4: preview mode records tool calls without executing them."""

    async def test_preview_mode_returns_preview_status(self) -> None:
        """run_flexible returns status='preview' when agent_mode='preview'."""
        llm_gw = _one_shot_llm("search")
        registry = _make_tool_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "preview-status",
            tools_allowed=["search"],
            agent_mode="preview",
        )

        result = await runner.run_flexible(
            config, user_message="preview me", session={}
        )

        assert result["status"] == "preview"

    async def test_preview_mode_returns_plan_list(self) -> None:
        """run_flexible returns a non-empty 'plan' list in preview mode."""
        llm_gw = _one_shot_llm("search")
        registry = _make_tool_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "preview-plan",
            tools_allowed=["search"],
            agent_mode="preview",
        )

        result = await runner.run_flexible(config, user_message="show plan", session={})

        assert "plan" in result
        assert isinstance(result["plan"], list)
        assert len(result["plan"]) >= 1

    async def test_preview_mode_plan_entry_contains_tool_name(self) -> None:
        """Each plan entry records the tool name that would have been called."""
        llm_gw = _one_shot_llm("distribute")
        registry = _make_tool_registry("distribute")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "preview-tool-name",
            tools_allowed=["distribute"],
            agent_mode="preview",
        )

        result = await runner.run_flexible(
            config, user_message="what would run", session={}
        )

        assert result["plan"][0]["tool"] == "distribute"

    async def test_preview_mode_does_not_execute_tool(self) -> None:
        """The actual tool execute function is NOT called in preview mode."""
        llm_gw = _one_shot_llm("distribute")
        registry = _make_tool_registry("distribute")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "preview-no-exec",
            tools_allowed=["distribute"],
            agent_mode="preview",
        )

        await runner.run_flexible(config, user_message="dry run", session={})

        distribute_mock = registry.get("distribute")
        assert distribute_mock is not None
        distribute_mock.assert_not_awaited()

    async def test_preview_plan_entry_has_would_execute_at_timestamp(self) -> None:
        """Plan entry contains 'would_execute_at' timestamp string."""
        llm_gw = _one_shot_llm("search")
        registry = _make_tool_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "preview-timestamp",
            tools_allowed=["search"],
            agent_mode="preview",
        )

        result = await runner.run_flexible(config, user_message="plan", session={})

        assert "would_execute_at" in result["plan"][0]


# ---------------------------------------------------------------------------
# AC-T064-5: process mode backward compatibility
# ---------------------------------------------------------------------------


class TestProcessModeBackwardCompat:
    """AC-T064-5: process mode behaves identically to flexible mode."""

    async def test_process_mode_executes_distribute_tool(self) -> None:
        """distribute is executed normally in process mode."""
        llm_gw = _one_shot_llm("distribute")
        registry = _make_tool_registry("distribute")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "process-compat-distribute",
            tools_allowed=["distribute"],
            agent_mode="process",
        )

        result = await runner.run_flexible(config, user_message="run", session={})

        distribute_mock = registry.get("distribute")
        assert distribute_mock is not None
        distribute_mock.assert_awaited_once()
        assert result["status"] == "success"

    async def test_no_agent_mode_behaves_as_process(self) -> None:
        """Config without agent_mode defaults to process and executes tools normally."""
        llm_gw = _one_shot_llm("search")
        registry = _make_tool_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "default-process",
            tools_allowed=["search"],
            # agent_mode omitted
        )

        result = await runner.run_flexible(
            config, user_message="search something", session={}
        )

        search_mock = registry.get("search")
        assert search_mock is not None
        search_mock.assert_awaited_once()
        assert result["status"] == "success"
        assert result["results"][0]["tool"] == "search"

    async def test_process_mode_returns_standard_status_success(self) -> None:
        """process mode returns {'status': 'success'} (not 'preview')."""
        llm_gw = AsyncMock()
        llm_gw.chat.return_value = LLMResult(
            content="done",
            metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
        )
        registry = _make_tool_registry("search")
        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gw)
        config = _flexible_config(
            "process-success-status",
            tools_allowed=["search"],
            agent_mode="process",
        )

        result = await runner.run_flexible(config, user_message="hello", session={})

        assert result["status"] == "success"
        assert "plan" not in result


# ---------------------------------------------------------------------------
# SR-001: ToolDefinition.mutates_external_state drives analyze deny
# ---------------------------------------------------------------------------


class TestMutatesExternalStateAnalyzeDeny:
    """SR-001 follow-up: analyze mode reads `mutates_external_state` flag.

    Replaces hardcoded `_ANALYZE_DENIED_TOOLS` reliance — new side-effectful
    tools opt in via the flag instead of editing a frozenset elsewhere.
    """

    async def test_new_mutating_tool_auto_denied_under_analyze(self) -> None:
        from intellisource.agent.tools import AgentToolRegistry, ToolDefinition

        async def _fake_send_email(**kwargs: object) -> dict[str, object]:
            return {"status": "sent"}

        registry = AgentToolRegistry()
        registry._tools["send_email"] = ToolDefinition(
            name="send_email",
            description="Sends an email externally.",
            parameters={"type": "object", "properties": {}},
            execute=_fake_send_email,
            mutates_external_state=True,
        )
        registry._tools["search"] = ToolDefinition(
            name="search",
            description="Read-only search.",
            parameters={"type": "object", "properties": {}},
            execute=AsyncMock(return_value={"items": []}),
        )

        config = PipelineConfig.from_dict(
            {
                "name": "analyze-new-tool",
                "mode": "flexible",
                "tools_allowed": ["search", "send_email"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 1,
                "on_failure": "skip",
                "agent_mode": "analyze",
            }
        )

        # ToolPermissionResolver drops send_email even though it's NOT in the
        # legacy _ANALYZE_DENIED_TOOLS frozenset — proving the field, not the
        # hardcoded set, drives the decision.
        allowed = ToolPermissionResolver(registry).filter_tools(
            config, AgentMode.analyze
        )
        assert "search" in allowed
        assert "send_email" not in allowed

    async def test_legacy_distribute_still_denied_via_fallback_set(self) -> None:
        """Backward compatibility: ToolDefinition-less callables still hit the
        static fallback set so existing pipelines don't regress."""
        from intellisource.agent.tool_gating import _ANALYZE_DENIED_TOOLS

        # Registry that returns a raw callable (not a ToolDefinition) so the
        # field-based path can't decide — the fallback set takes over.
        async def _raw_distribute(**kw: object) -> dict[str, object]:
            return {}

        registry = MagicMock()
        registry.list_tools = MagicMock(return_value=["distribute", "search"])
        registry.get = MagicMock(side_effect=lambda n: _raw_distribute if n else None)

        config = PipelineConfig.from_dict(
            {
                "name": "legacy",
                "mode": "flexible",
                "tools_allowed": ["distribute", "search"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 1,
                "on_failure": "skip",
                "agent_mode": "analyze",
            }
        )

        allowed = ToolPermissionResolver(registry).filter_tools(
            config, AgentMode.analyze
        )
        assert "distribute" not in allowed
        assert "distribute" in _ANALYZE_DENIED_TOOLS
