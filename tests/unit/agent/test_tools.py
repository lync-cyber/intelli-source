"""Tests for AgentToolRegistry and pipeline YAML configs.

Covers:
- AC-066: Pipeline configs define correct tool sets and step constraints
- AC-T036-1: AgentToolRegistry registers `collect` tool (M-002)
- AC-T036-2: AgentToolRegistry registers `process` tool (M-003)
- AC-T036-3: AgentToolRegistry registers `distribute` tool (M-007)
- AC-T036-4: AgentToolRegistry registers `search` tool (M-008)
- AC-T036-5: AgentToolRegistry registers `get_content_detail` tool (M-009)
- AC-T036-6: Tool definitions include name/description/parameters/execute
- AC-T036-7: scheduled-collect.yaml: mode=strict,
             tools_allowed=[collect,process,distribute]
- AC-T036-8: instant-search.yaml: mode=flexible,
             tools_allowed=[search,get_content_detail,summarize_for_user]
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

# ------------------------------------------------------------------
# Lazy import helper (RED phase: expect ModuleNotFoundError)
# ------------------------------------------------------------------


def _import_tools() -> Any:
    """Import the tools module; raises ModuleNotFoundError in RED."""
    import intellisource.agent.tools as mod

    return mod


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def tools_mod() -> Any:
    """Return the tools module."""
    return _import_tools()


@pytest.fixture()
def registry(tools_mod: Any) -> Any:
    """Return an AgentToolRegistry with defaults registered."""
    reg = tools_mod.AgentToolRegistry()
    reg.register_defaults()
    return reg


# ==================================================================
# AC-T036-1: collect tool registered
# ==================================================================


class TestCollectTool:
    """Verify AgentToolRegistry registers the collect tool."""

    def test_collect_registered(self, registry: Any) -> None:
        """AC-T036-1: collect tool is present in registry."""
        tool = registry.get("collect")
        assert tool is not None
        assert tool.name == "collect"

    def test_collect_is_async_callable(self, registry: Any) -> None:
        """AC-T036-1: collect tool execute fn is async."""
        tool = registry.get("collect")
        assert inspect.iscoroutinefunction(tool.execute)

    def test_collect_description_non_empty(self, registry: Any) -> None:
        """AC-T036-1: collect tool has a non-empty description."""
        tool = registry.get("collect")
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0


# ==================================================================
# AC-T036-2: process tool registered
# ==================================================================


class TestProcessTool:
    """Verify AgentToolRegistry registers the process tool."""

    def test_process_registered(self, registry: Any) -> None:
        """AC-T036-2: process tool is present in registry."""
        tool = registry.get("process")
        assert tool is not None
        assert tool.name == "process"

    def test_process_is_async_callable(self, registry: Any) -> None:
        """AC-T036-2: process tool execute fn is async."""
        tool = registry.get("process")
        assert inspect.iscoroutinefunction(tool.execute)


# ==================================================================
# AC-T036-3: distribute tool registered
# ==================================================================


class TestDistributeTool:
    """Verify AgentToolRegistry registers the distribute tool."""

    def test_distribute_registered(self, registry: Any) -> None:
        """AC-T036-3: distribute tool is present in registry."""
        tool = registry.get("distribute")
        assert tool is not None
        assert tool.name == "distribute"

    def test_distribute_is_async_callable(self, registry: Any) -> None:
        """AC-T036-3: distribute tool execute fn is async."""
        tool = registry.get("distribute")
        assert inspect.iscoroutinefunction(tool.execute)


# ==================================================================
# AC-T036-4: search tool registered
# ==================================================================


class TestSearchTool:
    """Verify AgentToolRegistry registers the search tool."""

    def test_search_registered(self, registry: Any) -> None:
        """AC-T036-4: search tool is present in registry."""
        tool = registry.get("search")
        assert tool is not None
        assert tool.name == "search"

    def test_search_is_async_callable(self, registry: Any) -> None:
        """AC-T036-4: search tool execute fn is async."""
        tool = registry.get("search")
        assert inspect.iscoroutinefunction(tool.execute)


# ==================================================================
# AC-T036-5: get_content_detail tool registered
# ==================================================================


class TestGetContentDetailTool:
    """Verify AgentToolRegistry registers get_content_detail."""

    def test_get_content_detail_registered(self, registry: Any) -> None:
        """AC-T036-5: get_content_detail tool is present."""
        tool = registry.get("get_content_detail")
        assert tool is not None
        assert tool.name == "get_content_detail"

    def test_get_content_detail_is_async_callable(self, registry: Any) -> None:
        """AC-T036-5: get_content_detail execute fn is async."""
        tool = registry.get("get_content_detail")
        assert inspect.iscoroutinefunction(tool.execute)


# ==================================================================
# AC-T036-6: Tool definitions include all required fields
# ==================================================================


class TestToolDefinitionSchema:
    """Verify each tool has name, description, parameters, execute."""

    _EXPECTED_TOOLS = [
        "collect",
        "process",
        "distribute",
        "search",
        "get_content_detail",
    ]

    @pytest.mark.parametrize("tool_name", _EXPECTED_TOOLS)
    def test_tool_has_name(self, registry: Any, tool_name: str) -> None:
        """AC-T036-6: tool definition has a name field."""
        tool = registry.get(tool_name)
        assert tool.name == tool_name

    @pytest.mark.parametrize("tool_name", _EXPECTED_TOOLS)
    def test_tool_has_description(self, registry: Any, tool_name: str) -> None:
        """AC-T036-6: tool definition has a description str."""
        tool = registry.get(tool_name)
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    @pytest.mark.parametrize("tool_name", _EXPECTED_TOOLS)
    def test_tool_has_json_schema_parameters(
        self, registry: Any, tool_name: str
    ) -> None:
        """AC-T036-6: tool parameters is a JSON Schema dict."""
        tool = registry.get(tool_name)
        params = tool.parameters
        assert isinstance(params, dict)
        # JSON Schema must declare a type
        assert "type" in params

    @pytest.mark.parametrize("tool_name", _EXPECTED_TOOLS)
    def test_tool_has_execute_callable(self, registry: Any, tool_name: str) -> None:
        """AC-T036-6: tool has an async execute callable."""
        tool = registry.get(tool_name)
        assert callable(tool.execute)
        assert inspect.iscoroutinefunction(tool.execute)


# ==================================================================
# AC-T036-6 (cont.): Registry API basics
# ==================================================================


class TestRegistryAPI:
    """Verify AgentToolRegistry core API methods."""

    def test_list_tools_returns_all_defaults(self, registry: Any) -> None:
        """AC-T036-6: list_tools returns all 6 built-in names."""
        names = registry.list_tools()
        expected = {
            "collect",
            "process",
            "distribute",
            "search",
            "get_content_detail",
            "summarize_for_user",
        }
        assert set(names) == expected

    def test_get_unknown_tool_returns_none_or_raises(self, registry: Any) -> None:
        """AC-T036-6: get() for unknown tool returns None or raises."""
        result = registry.get("nonexistent_tool")
        assert result is None

    def test_register_custom_tool(self, tools_mod: Any) -> None:
        """AC-T036-6: register() adds a new tool to registry."""

        async def _noop(**kwargs: Any) -> dict[str, str]:
            return {"status": "ok"}

        reg = tools_mod.AgentToolRegistry()
        reg.register(
            name="custom",
            description="A custom tool",
            parameters={"type": "object", "properties": {}},
            execute_fn=_noop,
        )
        tool = reg.get("custom")
        assert tool is not None
        assert tool.name == "custom"

    def test_filter_by_allowed(self, registry: Any) -> None:
        """AC-T036-6: filter(allowed=...) returns subset."""
        filtered = registry.filter(allowed=["collect", "search"])
        # filtered should contain exactly 2 tools
        if isinstance(filtered, dict):
            assert set(filtered.keys()) == {
                "collect",
                "search",
            }
        else:
            names = filtered.list_tools()
            assert set(names) == {"collect", "search"}

    def test_filter_by_denied(self, registry: Any) -> None:
        """AC-T036-6: filter(denied=...) excludes named tools."""
        filtered = registry.filter(denied=["collect"])
        if isinstance(filtered, dict):
            assert "collect" not in filtered
        else:
            assert "collect" not in filtered.list_tools()


# ==================================================================
# AC-T036-7: scheduled-collect.yaml pipeline config
# ==================================================================


class TestScheduledCollectPipeline:
    """Verify scheduled-collect pipeline YAML correctness."""

    def test_scheduled_collect_yaml_exists(self, tools_mod: Any) -> None:
        """AC-T036-7: scheduled-collect.yaml can be loaded."""
        config = tools_mod.load_pipeline_config("scheduled-collect")
        assert config is not None

    def test_scheduled_collect_mode_is_strict(self, tools_mod: Any) -> None:
        """AC-T036-7: scheduled-collect mode must be strict."""
        config = tools_mod.load_pipeline_config("scheduled-collect")
        assert config.mode == "strict"

    def test_scheduled_collect_tools_allowed(self, tools_mod: Any) -> None:
        """AC-T036-7: tools_allowed includes collect, distribute, and atomic tools."""
        config = tools_mod.load_pipeline_config("scheduled-collect")
        allowed = set(config.tools_allowed)
        assert "collect" in allowed
        assert "distribute" in allowed
        assert "regex_extract" in allowed

    def test_scheduled_collect_has_steps(self, tools_mod: Any) -> None:
        """AC-T036-7: scheduled-collect defines at least 1 step."""
        config = tools_mod.load_pipeline_config("scheduled-collect")
        assert len(config.steps) >= 1


# ==================================================================
# AC-T036-8: instant-search.yaml pipeline config
# ==================================================================


class TestInstantSearchPipeline:
    """Verify instant-search pipeline YAML correctness."""

    def test_instant_search_yaml_exists(self, tools_mod: Any) -> None:
        """AC-T036-8: instant-search.yaml can be loaded."""
        config = tools_mod.load_pipeline_config("instant-search")
        assert config is not None

    def test_instant_search_mode_is_flexible(self, tools_mod: Any) -> None:
        """AC-T036-8: instant-search mode must be flexible."""
        config = tools_mod.load_pipeline_config("instant-search")
        assert config.mode == "flexible"

    def test_instant_search_tools_allowed(self, tools_mod: Any) -> None:
        """AC-T036-8: tools_allowed includes search, get_content_detail,
        summarize_for_user, and atomic tools."""
        config = tools_mod.load_pipeline_config("instant-search")
        allowed = set(config.tools_allowed)
        assert "search" in allowed
        assert "get_content_detail" in allowed
        assert "summarize_for_user" in allowed

    def test_instant_search_has_steps(self, tools_mod: Any) -> None:
        """AC-T036-8: instant-search defines at least 1 step."""
        config = tools_mod.load_pipeline_config("instant-search")
        assert len(config.steps) >= 1


# ==================================================================
# AC-066: Pipeline configs define correct tool sets (cross-cutting)
# ==================================================================


class TestPipelineToolConstraints:
    """Cross-cutting checks on pipeline config tool constraints."""

    def test_strict_pipeline_does_not_allow_search(self, tools_mod: Any) -> None:
        """AC-066: scheduled-collect (strict) must NOT allow search."""
        config = tools_mod.load_pipeline_config("scheduled-collect")
        assert "search" not in config.tools_allowed

    def test_flexible_pipeline_does_not_allow_collect(self, tools_mod: Any) -> None:
        """AC-066: instant-search (flexible) must NOT allow collect."""
        config = tools_mod.load_pipeline_config("instant-search")
        assert "collect" not in config.tools_allowed


# ==================================================================
# Edge cases
# ==================================================================


class TestRegistryEdgeCases:
    """Edge cases and boundary conditions for the registry."""

    def test_register_defaults_is_idempotent(self, tools_mod: Any) -> None:
        """AC-T036-6: calling register_defaults twice does not
        duplicate tools."""
        reg = tools_mod.AgentToolRegistry()
        reg.register_defaults()
        reg.register_defaults()
        assert len(reg.list_tools()) == 6

    def test_filter_with_empty_allowed_returns_empty(self, registry: Any) -> None:
        """AC-T036-6: filter(allowed=[]) returns no tools."""
        filtered = registry.filter(allowed=[])
        if isinstance(filtered, dict):
            assert len(filtered) == 0
        else:
            assert len(filtered.list_tools()) == 0


# ==================================================================
# T-050: Atomic tool registration + llm_complete meta-tool
# ==================================================================

_ATOMIC_TOOL_NAMES = [
    "regex_extract",
    "fingerprint_generate",
    "vector_search_similar",
    "fingerprint_dedup",
    "find_nearest_cluster",
    "tfidf_keywords",
    "truncate_summary",
    "keyword_tag",
    "filter_sensitive",
    "truncate_for_push",
]


@pytest.fixture()
def full_registry(tools_mod: Any) -> Any:
    """Registry with defaults + atomic tools registered."""
    reg = tools_mod.AgentToolRegistry()
    reg.register_defaults()
    reg.register_atomic_tools()
    return reg


class TestRegisterAtomicTools:
    """AC-T050-1: register_atomic_tools() registers all 10 atomic tools."""

    @pytest.mark.parametrize("tool_name", _ATOMIC_TOOL_NAMES)
    def test_atomic_tool_registered(self, full_registry: Any, tool_name: str) -> None:
        """AC-T050-1: each atomic tool is present after registration."""
        tool = full_registry.get(tool_name)
        assert tool is not None, f"Tool {tool_name!r} not found in registry"
        assert tool.name == tool_name


class TestAtomicToolDefinitions:
    """AC-T050-2: Each atomic tool has name/description/parameters/execute."""

    @pytest.mark.parametrize("tool_name", _ATOMIC_TOOL_NAMES)
    def test_has_description(self, full_registry: Any, tool_name: str) -> None:
        """AC-T050-2: atomic tool has non-empty description."""
        tool = full_registry.get(tool_name)
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    @pytest.mark.parametrize("tool_name", _ATOMIC_TOOL_NAMES)
    def test_has_json_schema_params(self, full_registry: Any, tool_name: str) -> None:
        """AC-T050-2: atomic tool parameters is a JSON Schema dict."""
        tool = full_registry.get(tool_name)
        assert isinstance(tool.parameters, dict)
        assert "type" in tool.parameters

    @pytest.mark.parametrize("tool_name", _ATOMIC_TOOL_NAMES)
    def test_has_async_execute(self, full_registry: Any, tool_name: str) -> None:
        """AC-T050-2: atomic tool execute is an async callable."""
        tool = full_registry.get(tool_name)
        assert callable(tool.execute)
        assert inspect.iscoroutinefunction(tool.execute)


class TestLLMCompleteTool:
    """AC-T050-3: llm_complete meta-tool registration."""

    def test_llm_complete_registered(self, full_registry: Any) -> None:
        """AC-T050-3: llm_complete tool exists after register_atomic_tools."""
        tool = full_registry.get("llm_complete")
        assert tool is not None
        assert tool.name == "llm_complete"

    def test_llm_complete_has_call_type_param(self, full_registry: Any) -> None:
        """AC-T050-3: llm_complete parameters include call_type."""
        tool = full_registry.get("llm_complete")
        props = tool.parameters.get("properties", {})
        assert "call_type" in props
        assert props["call_type"]["type"] == "string"

    def test_llm_complete_has_prompt_vars_param(self, full_registry: Any) -> None:
        """AC-T050-3: llm_complete parameters include prompt_vars."""
        tool = full_registry.get("llm_complete")
        props = tool.parameters.get("properties", {})
        assert "prompt_vars" in props
        assert props["prompt_vars"]["type"] == "object"

    def test_llm_complete_is_async(self, full_registry: Any) -> None:
        """AC-T050-3: llm_complete execute is async."""
        tool = full_registry.get("llm_complete")
        assert inspect.iscoroutinefunction(tool.execute)


class TestListToolsWithAtomics:
    """AC-T050-4: list_tools() returns atomic + llm_complete + high-level."""

    def test_list_includes_all_tool_types(self, full_registry: Any) -> None:
        """AC-T050-4: list_tools includes atomics + llm_complete + defaults."""
        names = set(full_registry.list_tools())
        # 6 defaults + 10 atomics + 1 llm_complete = 17
        assert len(names) == 17
        for atomic in _ATOMIC_TOOL_NAMES:
            assert atomic in names, f"{atomic!r} missing from list_tools()"
        assert "llm_complete" in names
        assert "collect" in names  # one of the defaults


class TestFilterWithAtomics:
    """AC-T050-5: filter(allowed/denied) works for new tools."""

    def test_filter_allows_atomic_tool(self, full_registry: Any) -> None:
        """AC-T050-5: filter(allowed=...) includes an atomic tool."""
        filtered = full_registry.filter(allowed=["regex_extract", "collect"])
        assert "regex_extract" in filtered
        assert "collect" in filtered
        assert len(filtered) == 2

    def test_filter_denies_atomic_tool(self, full_registry: Any) -> None:
        """AC-T050-5: filter(denied=...) excludes atomic tools."""
        filtered = full_registry.filter(denied=["regex_extract", "llm_complete"])
        assert "regex_extract" not in filtered
        assert "llm_complete" not in filtered
        assert "collect" in filtered  # defaults still present
