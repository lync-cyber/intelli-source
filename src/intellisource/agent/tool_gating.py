"""Tool permission gating — single source of truth for the agent loop.

Resolves which tools an agent may call given pipeline config + agent mode:
filtering by allow/deny lists and per-tool permission levels, building the
OpenAI-style descriptors handed to the LLM, and deciding analyze-mode denial.
"""

from __future__ import annotations

from typing import Any

from intellisource.agent.tools import PermissionLevel, ToolDefinition

# Fallback set for callers that register tools without the
# ``ToolDefinition.mutates_external_state`` flag.
_ANALYZE_DENIED_TOOLS: frozenset[str] = frozenset({"distribute", "process"})


def _is_analyze_mode(agent_mode: Any) -> bool:
    """Return True when agent_mode represents analyze."""
    # AgentMode is a str-enum; .value works for enum instances and raw strings.
    val = agent_mode.value if hasattr(agent_mode, "value") else str(agent_mode)
    return val == "analyze"


def _is_preview_mode(agent_mode: Any) -> bool:
    """Return True when agent_mode represents preview."""
    val = agent_mode.value if hasattr(agent_mode, "value") else str(agent_mode)
    return val == "preview"


class ToolPermissionResolver:
    """Resolves tool availability and descriptors for one agent-loop turn.

    Constructed with the tool registry; stateless beyond it so a single
    instance is shared by AgentRunner and FlexibleLoop.
    """

    def __init__(self, tool_registry: Any) -> None:
        self._tool_registry = tool_registry

    def filter_tools(self, config: Any, agent_mode: Any) -> list[str]:
        """Build available tool list respecting config filters and permission levels."""
        all_tools: list[str] = self._tool_registry.list_tools()
        denied = set(config.tools_denied)
        allowed = set(config.tools_allowed)

        if _is_analyze_mode(agent_mode):
            denied = denied | self._analyze_denied_tools(all_tools)

        if allowed:
            tools = [t for t in all_tools if t in allowed]
        else:
            tools = list(all_tools)

        # Resolve effective permission per tool (pipeline override > tool default).
        pipeline_perms: dict[str, str] = getattr(config, "tool_permissions", {}) or {}
        permission_denied: set[str] = set()
        for t in tools:
            override = pipeline_perms.get(t)
            if override is not None:
                effective = PermissionLevel(override)
            else:
                tool_def = self._tool_registry.get(t)
                effective = (
                    tool_def.permission_level
                    if isinstance(tool_def, ToolDefinition)
                    else PermissionLevel.auto
                )
            if effective is PermissionLevel.deny:
                permission_denied.add(t)

        return [t for t in tools if t not in denied and t not in permission_denied]

    def is_analyze_denied(self, name: str, agent_mode: Any) -> bool:
        """Return True when ``name`` is denied under analyze mode."""
        if not _is_analyze_mode(agent_mode):
            return False
        return self._is_analyze_denied_name(name)

    def build_tool_descriptors(self, tool_names: list[str]) -> list[dict[str, Any]]:
        """Build OpenAI-style function tool descriptors for LLMGateway.chat()."""
        descriptors: list[dict[str, Any]] = []
        for name in tool_names:
            tool = self._tool_registry.get(name)
            if isinstance(tool, ToolDefinition):
                description = tool.description
                parameters = tool.parameters
            else:
                description = ""
                parameters = {"type": "object", "properties": {}}
            descriptors.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
        return descriptors

    def _analyze_denied_tools(self, candidate_names: list[str]) -> set[str]:
        return {n for n in candidate_names if self._is_analyze_denied_name(n)}

    def _is_analyze_denied_name(self, name: str) -> bool:
        tool_def = self._tool_registry.get(name)
        if isinstance(tool_def, ToolDefinition) and tool_def.mutates_external_state:
            return True
        return name in _ANALYZE_DENIED_TOOLS
