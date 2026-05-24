"""Tests for tool permission level governance (T-065).

Covers AC-T065-1 through AC-T065-7:
- ToolDefinition gains permission_level field (auto/confirm/deny)
- auto tools execute normally
- deny tools are filtered from descriptors and blocked at runtime
- pipeline YAML supports tool_permissions override section
- distribute defaults to confirm
- mypy --strict: verified by CI
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.runner import AgentRunner
from intellisource.agent.tools import AgentToolRegistry, PermissionLevel, ToolDefinition
from intellisource.llm.gateway import LLMResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry_with_perms(
    tools: dict[str, PermissionLevel],
) -> AgentToolRegistry:
    """Build a real AgentToolRegistry with given tool names and permission levels."""
    registry = AgentToolRegistry()
    for name, level in tools.items():
        registry.register(
            name=name,
            description=f"tool {name}",
            parameters={"type": "object", "properties": {}},
            execute_fn=AsyncMock(return_value={"result": name}),
            permission_level=level,
        )
    return registry


def _flexible_config_with_permissions(
    name: str,
    tools_allowed: list[str],
    tool_permissions: dict[str, str] | None = None,
    max_steps: int = 5,
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
    if tool_permissions is not None:
        data["tool_permissions"] = tool_permissions
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

    llm_gw.chat = AsyncMock(side_effect=_chat)
    return llm_gw


# ---------------------------------------------------------------------------
# AC-T065-1: ToolDefinition has permission_level field
# ---------------------------------------------------------------------------


class TestPermissionLevelField:
    def test_tool_definition_default_is_auto(self) -> None:
        """ToolDefinition without explicit permission_level defaults to auto."""
        td = ToolDefinition(
            name="test",
            description="d",
            parameters={},
            execute=AsyncMock(),
        )
        assert td.permission_level is PermissionLevel.auto

    def test_tool_definition_explicit_confirm(self) -> None:
        """ToolDefinition can be constructed with confirm level."""
        td = ToolDefinition(
            name="test",
            description="d",
            parameters={},
            execute=AsyncMock(),
            permission_level=PermissionLevel.confirm,
        )
        assert td.permission_level is PermissionLevel.confirm

    def test_permission_level_enum_values(self) -> None:
        """PermissionLevel enum has auto, confirm, deny string values."""
        assert PermissionLevel.auto.value == "auto"
        assert PermissionLevel.confirm.value == "confirm"
        assert PermissionLevel.deny.value == "deny"


# ---------------------------------------------------------------------------
# AC-T065-2 / AC-T065-4: auto executes, deny is filtered and blocked
# ---------------------------------------------------------------------------


class TestDenyHardFilter:
    @pytest.mark.asyncio
    async def test_deny_tool_not_in_descriptors(self) -> None:
        """deny-level tool must not appear in LLM tool descriptors."""
        registry = _make_registry_with_perms(
            {"safe": PermissionLevel.auto, "dangerous": PermissionLevel.deny}
        )
        config = _flexible_config_with_permissions("p", ["safe", "dangerous"])
        runner = AgentRunner(registry, _one_shot_llm(), pipeline_engine=None)
        available = runner._filter_tools(config)
        assert "dangerous" not in available
        assert "safe" in available

    @pytest.mark.asyncio
    async def test_deny_tool_runtime_hallucination_blocked(self) -> None:
        """LLM hallucinating a deny tool at runtime returns denied_by_permission."""
        registry = _make_registry_with_perms(
            {"safe": PermissionLevel.auto, "dangerous": PermissionLevel.deny}
        )
        config = _flexible_config_with_permissions("p", ["safe", "dangerous"])
        llm = _one_shot_llm("dangerous")
        runner = AgentRunner(registry, llm, pipeline_engine=None)
        result = await runner.run_flexible(config, user_message="go", session={})
        denied_results = [
            r
            for r in result.get("results", [])
            if r.get("status") == "denied_by_permission"
        ]
        assert len(denied_results) == 1
        assert denied_results[0]["tool"] == "dangerous"

    @pytest.mark.asyncio
    async def test_auto_tool_executes_normally(self) -> None:
        """auto-level tool executes and its output appears in tool_results."""
        registry = _make_registry_with_perms({"safe": PermissionLevel.auto})
        config = _flexible_config_with_permissions("p", ["safe"])
        llm = _one_shot_llm("safe")
        runner = AgentRunner(registry, llm, pipeline_engine=None)
        result = await runner.run_flexible(config, user_message="go", session={})
        executed = [r for r in result.get("results", []) if r.get("tool") == "safe"]
        assert len(executed) == 1
        assert executed[0].get("output") is not None


# ---------------------------------------------------------------------------
# AC-T065-3: confirm tool records pending_confirmation event
# ---------------------------------------------------------------------------


class TestConfirmPendingEvent:
    @pytest.mark.asyncio
    async def test_confirm_tool_records_pending_confirmation(self) -> None:
        """confirm-level tool call records a pending_confirmation entry."""
        registry = _make_registry_with_perms({"distribute": PermissionLevel.confirm})
        config = _flexible_config_with_permissions("p", ["distribute"])
        llm = _one_shot_llm("distribute")
        runner = AgentRunner(registry, llm, pipeline_engine=None)
        result = await runner.run_flexible(config, user_message="go", session={})
        pending = [
            r
            for r in result.get("results", [])
            if r.get("status") == "pending_confirmation"
        ]
        assert len(pending) == 1
        assert pending[0]["tool"] == "distribute"
        assert "args" in pending[0]
        assert "tool_call_id" in pending[0]


# ---------------------------------------------------------------------------
# AC-T065-5: PipelineConfig tool_permissions override
# ---------------------------------------------------------------------------


class TestPipelinePermissionOverride:
    def test_pipeline_tool_permissions_valid(self) -> None:
        """tool_permissions section loads valid auto/confirm/deny values."""
        cfg = _flexible_config_with_permissions(
            "p",
            ["collect", "distribute"],
            tool_permissions={"collect": "deny", "distribute": "confirm"},
        )
        assert cfg.tool_permissions == {"collect": "deny", "distribute": "confirm"}

    def test_pipeline_tool_permissions_invalid_raises(self) -> None:
        """tool_permissions with invalid level raises ValueError."""
        with pytest.raises(ValueError, match="invalid"):
            _flexible_config_with_permissions(
                "p",
                ["collect"],
                tool_permissions={"collect": "superuser"},
            )

    def test_pipeline_tool_permissions_override_default(self) -> None:
        """Pipeline tool_permissions deny overrides ToolDefinition default auto."""
        registry = _make_registry_with_perms(
            {"safe": PermissionLevel.auto, "guarded": PermissionLevel.auto}
        )
        config = _flexible_config_with_permissions(
            "p", ["safe", "guarded"], tool_permissions={"guarded": "deny"}
        )
        runner = AgentRunner(registry, _one_shot_llm(), pipeline_engine=None)
        available = runner._filter_tools(config)
        assert "guarded" not in available
        assert "safe" in available


# ---------------------------------------------------------------------------
# AC-T065-6: distribute defaults to confirm in register_defaults
# ---------------------------------------------------------------------------


class TestDistributeDefaultsConfirm:
    def test_distribute_permission_level_is_confirm(self) -> None:
        """distribute registered via register_defaults has permission_level=confirm."""
        registry = AgentToolRegistry()
        registry.register_defaults()
        tool = registry.get("distribute")
        assert tool is not None
        assert tool.permission_level is PermissionLevel.confirm

    def test_other_defaults_are_auto(self) -> None:
        """Other default tools (collect, search, etc.) have permission_level=auto."""
        registry = AgentToolRegistry()
        registry.register_defaults()
        auto_tools = (
            "collect",
            "process",
            "search",
            "get_content_detail",
            "summarize_for_user",
        )
        for name in auto_tools:
            tool = registry.get(name)
            assert tool is not None, f"Missing default tool: {name}"
            assert tool.permission_level is PermissionLevel.auto, (
                f"Expected auto for {name}, got {tool.permission_level}"
            )
