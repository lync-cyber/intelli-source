"""Agent tool registry and pipeline config loader.

Provides AgentToolRegistry for registering tools that can be invoked
by AgentRunner, and load_pipeline_config for loading YAML pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine

from intellisource.agent.pipeline import PipelineConfig

_PIPELINES_DIR = Path(__file__).resolve().parents[3] / "config" / "pipelines"


@dataclass
class ToolDefinition:
    """A single tool that can be invoked by the agent."""

    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[..., Coroutine[Any, Any, Any]]


class AgentToolRegistry:
    """Registry of agent-callable tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        execute_fn: Callable[..., Coroutine[Any, Any, Any]],
    ) -> None:
        """Register a tool definition."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            execute=execute_fn,
        )

    def register_defaults(self) -> None:
        """Register the five built-in tools."""
        defaults = _default_tool_defs()
        for defn in defaults:
            self._tools[defn.name] = defn

    def get(self, name: str) -> ToolDefinition | None:
        """Return tool by name, or None if not found."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return names of all registered tools."""
        return list(self._tools.keys())

    def filter(
        self,
        *,
        allowed: list[str] | None = None,
        denied: list[str] | None = None,
    ) -> dict[str, ToolDefinition]:
        """Return a filtered subset of tools."""
        result = dict(self._tools)
        if allowed is not None:
            allowed_set = set(allowed)
            result = {k: v for k, v in result.items() if k in allowed_set}
        if denied is not None:
            denied_set = set(denied)
            result = {k: v for k, v in result.items() if k not in denied_set}
        return result


def load_pipeline_config(name: str) -> PipelineConfig:
    """Load a pipeline config YAML by name from the pipelines dir."""
    path = _PIPELINES_DIR / f"{name}.yaml"
    return PipelineConfig.from_yaml(str(path))


# -------------------------------------------------------------------
# Default tool definitions
# -------------------------------------------------------------------


async def _collect_execute(**kwargs: Any) -> dict[str, Any]:
    """Placeholder: invoke M-002 collector engine."""
    return {"status": "ok", "tool": "collect", **kwargs}


async def _process_execute(**kwargs: Any) -> dict[str, Any]:
    """Placeholder: invoke M-003 processing pipeline."""
    return {"status": "ok", "tool": "process", **kwargs}


async def _distribute_execute(**kwargs: Any) -> dict[str, Any]:
    """Placeholder: invoke M-007 distribution."""
    return {"status": "ok", "tool": "distribute", **kwargs}


async def _search_execute(**kwargs: Any) -> dict[str, Any]:
    """Placeholder: invoke M-008 hybrid search engine."""
    return {"status": "ok", "tool": "search", **kwargs}


async def _get_content_detail_execute(**kwargs: Any) -> dict[str, Any]:
    """Placeholder: invoke M-009 content detail retrieval."""
    return {"status": "ok", "tool": "get_content_detail", **kwargs}


def _default_tool_defs() -> list[ToolDefinition]:
    """Return the five built-in tool definitions."""
    return [
        ToolDefinition(
            name="collect",
            description="Collect content from configured sources (RSS, web, etc.)",
            parameters={
                "type": "object",
                "properties": {
                    "source_type": {"type": "string"},
                    "source_id": {"type": "string"},
                },
            },
            execute=_collect_execute,
        ),
        ToolDefinition(
            name="process",
            description="Process raw content through the cleaning/extraction pipeline.",
            parameters={
                "type": "object",
                "properties": {
                    "pipeline": {"type": "string"},
                    "content_id": {"type": "string"},
                },
            },
            execute=_process_execute,
        ),
        ToolDefinition(
            name="distribute",
            description=(
                "Distribute processed content to subscribers via configured channels."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "channels": {"type": "string"},
                    "content_id": {"type": "string"},
                },
            },
            execute=_distribute_execute,
        ),
        ToolDefinition(
            name="search",
            description="Search the knowledge base using keyword and semantic search.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
            },
            execute=_search_execute,
        ),
        ToolDefinition(
            name="get_content_detail",
            description="Retrieve detailed content by ID.",
            parameters={
                "type": "object",
                "properties": {
                    "content_id": {"type": "string"},
                },
            },
            execute=_get_content_detail_execute,
        ),
    ]
