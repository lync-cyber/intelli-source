"""Agent tool registry and pipeline config loader.

Provides AgentToolRegistry for registering tools that can be invoked
by AgentRunner, and load_pipeline_config for loading YAML pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine

from intellisource.agent.pipeline import PipelineConfig
from intellisource.pipeline.processors import tools as atomic_tools

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

    def register_atomic_tools(self) -> None:
        """Register all 10 atomic processing tools + llm_complete meta-tool."""
        defs = _atomic_tool_defs()
        for defn in defs:
            self._tools[defn.name] = defn

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


async def _collect_execute(
    source_id: str = "",
    source_type: str = "",
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke CollectorRegistry.get(source_type).collect() for the given source."""
    if tool_deps is not None and tool_deps.collector_registry is not None:
        collector = tool_deps.collector_registry.get(source_type)
        if collector is not None:
            collected = await collector.collect(source_id=source_id, **kwargs)
            return {"status": "ok", "tool": "collect", "collected": collected}
    return {"status": "ok", "tool": "collect", "collected": [], "source_id": source_id}


async def _process_execute(
    content_id: str = "",
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke PipelineEngine.execute() for the given content_id."""
    if tool_deps is not None and tool_deps.pipeline_engine is not None:
        result = await tool_deps.pipeline_engine.execute(
            content_id=content_id, **kwargs
        )
        return {"status": "ok", "tool": "process", "result": result}
    return {"status": "ok", "tool": "process", "content_id": content_id}


async def _distribute_execute(
    content_id: str = "",
    subscription_id: str = "",
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke distributor.distribute() for the given content and subscription."""
    if tool_deps is not None and tool_deps.distributor is not None:
        result = await tool_deps.distributor.distribute(
            content_id=content_id,
            subscription_id=subscription_id,
            **kwargs,
        )
        return {"status": "ok", "tool": "distribute", "result": result}
    return {"status": "ok", "tool": "distribute", "content_id": content_id}


async def _search_execute(
    query: str = "",
    top_k: int = 10,
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke HybridSearchEngine.search() with the given query."""
    if tool_deps is not None and tool_deps.search_engine is not None:
        response = await tool_deps.search_engine.search(
            query=query, top_k=top_k, **kwargs
        )
        return {"status": "ok", "tool": "search", "response": response}
    return {"status": "ok", "tool": "search", "query": query}


async def _get_content_detail_execute(
    content_id: str = "",
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke ContentRepository.get_by_id() for the given content_id."""
    from intellisource.storage.repositories.content import ContentRepository

    if tool_deps is not None and tool_deps.session_factory is not None:
        session = tool_deps.session_factory()
        async with session as s:
            repo = ContentRepository(session=s)
            content = await repo.get_by_id(content_id)
            return {
                "status": "ok",
                "tool": "get_content_detail",
                "content": content,
                "content_id": content_id,
            }
    return {"status": "ok", "tool": "get_content_detail", "content_id": content_id}


async def _summarize_for_user_execute(
    content_id: str = "",
    content: str = "",
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke LLMGateway.complete() to generate a user-facing summary."""
    if tool_deps is not None and tool_deps.llm_gateway is not None:
        prompt = f"Summarize the following content:\n\n{content}"
        result = await tool_deps.llm_gateway.complete(
            prompt=prompt, task_type="summarize"
        )
        return {
            "status": "ok",
            "tool": "summarize_for_user",
            "summary": result.content,
            "content_id": content_id,
        }
    return {"status": "ok", "tool": "summarize_for_user", "content_id": content_id}


async def _llm_complete_execute(
    call_type: str = "",
    prompt_vars: dict[str, Any] | None = None,
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke LLMGateway for a specific call_type with prompt_vars."""
    if prompt_vars is None:
        prompt_vars = {}
    prompt = (
        " ".join(f"{k}: {v}" for k, v in prompt_vars.items())
        if prompt_vars
        else call_type
    )
    gateway = tool_deps.llm_gateway if tool_deps is not None else None
    if gateway is None:
        return {"status": "ok", "tool": "llm_complete", "call_type": call_type}
    result = await gateway.complete(prompt=prompt, task_type=call_type or None)
    return {
        "content": result.content,
        "call_type": call_type,
        "metadata": result.metadata,
    }


def _atomic_tool_defs() -> list[ToolDefinition]:
    """Return the 10 atomic tool definitions + llm_complete meta-tool."""
    return [
        ToolDefinition(
            name="regex_extract",
            description="Extract structured data from text using regex patterns.",
            parameters={
                "type": "object",
                "properties": {
                    "body_text": {"type": "string"},
                    "patterns": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
                "required": ["body_text"],
            },
            execute=atomic_tools.regex_extract,
        ),
        ToolDefinition(
            name="fingerprint_generate",
            description="Generate a SHA-256 fingerprint from title and body text.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body_text": {"type": "string"},
                },
                "required": ["title", "body_text"],
            },
            execute=atomic_tools.fingerprint_generate,
        ),
        ToolDefinition(
            name="vector_search_similar",
            description="Search for similar content via vector store.",
            parameters={
                "type": "object",
                "properties": {
                    "embedding": {"type": "array", "items": {"type": "number"}},
                    "threshold": {"type": "number"},
                    "vector_store": {"type": "object"},
                },
                "required": ["embedding", "threshold", "vector_store"],
            },
            execute=atomic_tools.vector_search_similar,
        ),
        ToolDefinition(
            name="fingerprint_dedup",
            description="Check if content is a duplicate by SHA-256 fingerprint.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body_text": {"type": "string"},
                    "known_fingerprints": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["title", "body_text", "known_fingerprints"],
            },
            execute=atomic_tools.fingerprint_dedup,
        ),
        ToolDefinition(
            name="find_nearest_cluster",
            description="Find the nearest existing cluster for an embedding.",
            parameters={
                "type": "object",
                "properties": {
                    "embedding": {"type": "array", "items": {"type": "number"}},
                    "threshold": {"type": "number"},
                    "vector_store": {"type": "object"},
                },
                "required": ["embedding", "threshold", "vector_store"],
            },
            execute=atomic_tools.find_nearest_cluster,
        ),
        ToolDefinition(
            name="tfidf_keywords",
            description="Extract TF-IDF-like top-5 keywords from title and body.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body_text": {"type": "string"},
                },
                "required": ["title", "body_text"],
            },
            execute=atomic_tools.tfidf_keywords,
        ),
        ToolDefinition(
            name="truncate_summary",
            description="Generate a digest from clustered documents via truncation.",
            parameters={
                "type": "object",
                "properties": {
                    "cluster_contents": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
                "required": ["cluster_contents"],
            },
            execute=atomic_tools.truncate_summary,
        ),
        ToolDefinition(
            name="keyword_tag",
            description="Tag content by matching keywords from a tag library.",
            parameters={
                "type": "object",
                "properties": {
                    "body_text": {"type": "string"},
                    "title": {"type": "string"},
                    "tag_library": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["body_text", "title", "tag_library"],
            },
            execute=atomic_tools.keyword_tag,
        ),
        ToolDefinition(
            name="filter_sensitive",
            description="Find sensitive words present in text.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "sensitive_words": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["text", "sensitive_words"],
            },
            execute=atomic_tools.filter_sensitive,
        ),
        ToolDefinition(
            name="truncate_for_push",
            description="Truncate content to push distribution lengths.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body_text": {"type": "string"},
                },
                "required": ["title", "body_text"],
            },
            execute=atomic_tools.truncate_for_push,
        ),
        ToolDefinition(
            name="llm_complete",
            description=(
                "Meta-tool: invoke LLM for a specific call_type with prompt variables."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "call_type": {"type": "string"},
                    "prompt_vars": {"type": "object"},
                },
                "required": ["call_type", "prompt_vars"],
            },
            execute=_llm_complete_execute,
        ),
    ]


def _default_tool_defs() -> list[ToolDefinition]:
    """Return the six built-in tool definitions."""
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
        ToolDefinition(
            name="summarize_for_user",
            description="Summarize retrieved content for user response.",
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "format": {"type": "string"},
                },
            },
            execute=_summarize_for_user_execute,
        ),
    ]
