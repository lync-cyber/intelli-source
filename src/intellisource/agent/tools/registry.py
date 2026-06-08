"""Tool registry primitives.

Defines:
- ``AgentToolRegistry`` — register/lookup/filter/auto-discover tools.
- ``_atomic_tool_defs`` / ``_default_tool_defs`` — built-in tool definitions
  installed by ``register_atomic_tools`` / ``register_defaults``.

``PermissionLevel`` / ``ToolDefinition`` are defined in
:mod:`intellisource.agent.tools._spec` and re-exported here for callers that
import them from this module. The control-plane (management + run) tool
definitions are co-located with their execute functions and pulled in as
``MANAGEMENT_TOOL_DEFS`` / ``RUN_TOOL_DEFS``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Coroutine

from intellisource.agent.tools._spec import PermissionLevel, ToolDefinition
from intellisource.agent.tools.executes.collect import _collect_execute
from intellisource.agent.tools.executes.distribute import _distribute_execute
from intellisource.agent.tools.executes.llm import _llm_complete_execute
from intellisource.agent.tools.executes.manage import MANAGEMENT_TOOL_DEFS
from intellisource.agent.tools.executes.process import _process_execute
from intellisource.agent.tools.executes.run import RUN_TOOL_DEFS
from intellisource.agent.tools.executes.search_and_content import (
    _get_content_detail_execute,
    _search_execute,
    _summarize_for_user_execute,
)
from intellisource.agent.tools.executes.summarize_cluster import summarize_cluster
from intellisource.observability.logging import get_logger
from intellisource.pipeline.processors import tools as atomic_tools

logger = get_logger(__name__)

__all__ = ["AgentToolRegistry", "PermissionLevel", "ToolDefinition"]

_DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parent


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
        permission_level: PermissionLevel = PermissionLevel.auto,
        mutates_external_state: bool = False,
    ) -> None:
        """Register a tool definition."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            execute=execute_fn,
            permission_level=permission_level,
            mutates_external_state=mutates_external_state,
        )

    def register_defaults(self) -> None:
        """Register the six built-in tools."""
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

    def register_management_tools(self) -> None:
        """Register control-plane tools: CRUD for sources / subscriptions /
        pipelines plus pipeline run-trigger (``run_pipeline``) and run-status
        (``get_task_status``).

        Gated by each pipeline's ``tools_allowed`` — only elevated definitions
        such as ``admin-agent`` expose them; ``analyze`` agent mode auto-denies
        the mutating ones via ``mutates_external_state``.
        """
        for defn in _management_tool_defs():
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

    def auto_discover(self, tools_dir: str | Path | None = None) -> None:
        """Scan tools_dir for plugin modules exporting TOOL_DEFINITION.

        Each *.py file (skipping __init__.py and dunder-prefixed names) is
        imported under a synthetic module name and inspected for a top-level
        TOOL_DEFINITION attribute of type ToolDefinition. Already-registered
        tool names take precedence (manual register wins over auto-discover).
        Import or attribute errors are logged at WARNING and skipped — they
        do not abort discovery of remaining files or application startup.
        """
        base = Path(tools_dir) if tools_dir is not None else _DEFAULT_PLUGINS_DIR
        if not base.is_dir():
            logger.warning(
                "auto_discover: tools_dir %s does not exist or is not a directory",
                base,
            )
            return

        for child in sorted(base.iterdir()):
            if not child.is_file() or child.suffix != ".py":
                continue
            if child.name.startswith("_"):
                continue

            module_name = f"intellisource.agent.tools._discovered.{child.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, str(child))
                if spec is None or spec.loader is None:
                    logger.warning("auto_discover: failed to build spec for %s", child)
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            except Exception as exc:
                logger.warning("auto_discover: import failed for %s: %s", child, exc)
                continue

            tool_def = getattr(module, "TOOL_DEFINITION", None)
            if tool_def is None:
                continue
            if not isinstance(tool_def, ToolDefinition):
                logger.warning(
                    "auto_discover: %s.TOOL_DEFINITION is not a ToolDefinition "
                    "(got %s); skipping",
                    child,
                    type(tool_def).__name__,
                )
                continue
            if tool_def.name in self._tools:
                continue
            self._tools[tool_def.name] = tool_def


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
            description=(
                "Generate a structured digest from clustered documents"
                " using LLM summarization with truncation fallback."
            ),
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
            execute=summarize_cluster,
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
            description="Collect content from a configured source (RSS, web, etc.)",
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "UUID of the source to collect from.",
                    },
                    "source_type": {
                        "type": "string",
                        "description": (
                            "Source adapter type (rss/web/api); inferred from the"
                            " source row when omitted."
                        ),
                    },
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
                    "content_id": {
                        "type": "string",
                        "description": "Single raw content UUID to process.",
                    },
                    "raw_content_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Batch of raw content UUIDs; takes precedence over"
                            " content_id when provided."
                        ),
                    },
                },
                # At least one content identifier must be supplied (single id or
                # the batch list); a call with neither is a no-op.
                "anyOf": [
                    {"required": ["content_id"]},
                    {"required": ["raw_content_ids"]},
                ],
            },
            execute=_process_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="distribute",
            description=(
                "Distribute processed content to subscribers via configured channels."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content_id": {
                        "type": "string",
                        "description": "Single processed content UUID to distribute.",
                    },
                    "processed_content_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Batch of processed content UUIDs; takes precedence over"
                            " content_id when provided."
                        ),
                    },
                    "subscription_id": {
                        "type": "string",
                        "description": (
                            "Target subscription UUID; when omitted, fans out to all"
                            " active subscriptions matching the content."
                        ),
                    },
                },
                # At least one content identifier is required (single id or the
                # batch list). subscription_id stays optional on purpose: omitting
                # it fans out to every matching active subscription.
                "anyOf": [
                    {"required": ["content_id"]},
                    {"required": ["processed_content_ids"]},
                ],
            },
            execute=_distribute_execute,
            permission_level=PermissionLevel.confirm,
            mutates_external_state=True,
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


def _management_tool_defs() -> list[ToolDefinition]:
    """Control-plane tool definitions: CRUD (sources / subscriptions / pipelines
    / templates) co-located in ``executes.manage`` plus the run-trigger /
    run-status tools co-located in ``executes.run``."""
    return [*MANAGEMENT_TOOL_DEFS, *RUN_TOOL_DEFS]
