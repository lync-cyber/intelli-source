"""Tool registry primitives.

Defines:
- ``PermissionLevel`` — tool invocation permission enum.
- ``ToolDefinition`` — single tool descriptor (name + JSON schema + execute fn).
- ``AgentToolRegistry`` — register/lookup/filter/auto-discover tools.
- ``_atomic_tool_defs`` / ``_default_tool_defs`` — built-in tool definitions
  installed by ``register_atomic_tools`` / ``register_defaults``.

The ``_execute`` callables live in :mod:`intellisource.agent.tools.executes`
and are imported here as the canonical sources.
"""

from __future__ import annotations

import enum
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

from intellisource.agent.tools.executes.collect import _collect_execute
from intellisource.agent.tools.executes.distribute import _distribute_execute
from intellisource.agent.tools.executes.llm import _llm_complete_execute
from intellisource.agent.tools.executes.manage import (
    _create_pipeline_execute,
    _create_source_execute,
    _create_subscription_execute,
    _create_template_execute,
    _delete_pipeline_execute,
    _delete_source_execute,
    _delete_subscription_execute,
    _delete_template_execute,
    _get_source_execute,
    _get_subscription_execute,
    _get_template_execute,
    _list_pipelines_execute,
    _list_sources_execute,
    _list_subscriptions_execute,
    _list_templates_execute,
    _update_pipeline_execute,
    _update_source_execute,
    _update_subscription_execute,
    _update_template_execute,
)
from intellisource.agent.tools.executes.process import _process_execute
from intellisource.agent.tools.executes.run import (
    _get_task_status_execute,
    _run_pipeline_execute,
)
from intellisource.agent.tools.executes.search_and_content import (
    _get_content_detail_execute,
    _search_execute,
    _summarize_for_user_execute,
)
from intellisource.observability.logging import get_logger
from intellisource.pipeline.processors import tools as atomic_tools

logger = get_logger(__name__)

_DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parent


class PermissionLevel(str, enum.Enum):
    """Tool invocation permission level.

    Values:
        auto: executed without confirmation (default for read-only tools).
        confirm: **confirm-as-logged** semantics — when invoked under
            ``run_flexible``, the runner records a ``pending_confirmation``
            event in 3 places (logger.info / tool_results entry / messages
            entry returned to the LLM) and skips actual execution for the
            current turn. The LLM observes the pending status via the next
            assistant turn and decides whether to retry, escalate or abort.
            **This is not a hard blocking-pause** — there is no callback
            wait or user-prompt loop in the runtime; production callers
            who need a true human-in-the-loop should subscribe to the
            ``pending_confirmation`` log event externally and re-issue
            the tool call with elevated permission once approved.
        deny: never executed; runner drops from tool descriptors at
            ``_filter_tools`` time and hard-rejects at runtime as a defence
            against LLM hallucination of denied tool names.
    """

    auto = "auto"
    confirm = "confirm"
    deny = "deny"


@dataclass
class ToolDefinition:
    """A single tool that can be invoked by the agent.

    Fields:
        mutates_external_state: True when the tool writes to a system the
            user can observe outside the agent (DB, message bus, webhook,
            outbound email, file system, etc.). Default False = read-only.
            ``analyze`` agent mode auto-denies tools where this is True so
            new side-effectful tools must opt in explicitly. Read-only tools
            (search/get/summarize) keep the default.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[..., Coroutine[Any, Any, Any]]
    permission_level: PermissionLevel = field(default=PermissionLevel.auto)
    mutates_external_state: bool = False


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
    """CRUD control-plane tools for sources / subscriptions / pipelines."""
    return [
        ToolDefinition(
            name="create_source",
            description="Create or update a data source (rss/api/web) by name.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["rss", "api", "web"]},
                    "url": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "discipline_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["name", "type", "url"],
            },
            execute=_create_source_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="list_sources",
            description="List configured data sources.",
            parameters={
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
            execute=_list_sources_execute,
        ),
        ToolDefinition(
            name="get_source",
            description=(
                "Fetch a single data source by id, returning its full"
                " configuration (name/type/url/status/tags/schedule)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "UUID of the source to fetch.",
                    }
                },
                "required": ["source_id"],
            },
            execute=_get_source_execute,
        ),
        ToolDefinition(
            name="update_source",
            description=(
                "Partially update an EXISTING data source by id. Only the fields"
                " you supply change; the source must already exist (use"
                " create_source to add a new one). Call get_source / list_sources"
                " first to confirm the id and current values."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "UUID of the source to update.",
                    },
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "discipline_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "schedule_interval": {"type": "integer"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused"],
                    },
                },
                "required": ["source_id"],
            },
            execute=_update_source_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="delete_source",
            description="Soft-delete (pause) a data source by id.",
            parameters={
                "type": "object",
                "properties": {"source_id": {"type": "string"}},
                "required": ["source_id"],
            },
            execute=_delete_source_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="create_subscription",
            description="Create a subscription on a channel (email/wechat/wework).",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "channel": {
                        "type": "string",
                        "enum": ["email", "wechat", "wework"],
                    },
                    "channel_config": {"type": "object"},
                    "match_rules": {"type": "object"},
                    "frequency": {"type": "string"},
                },
                "required": ["name", "channel"],
            },
            execute=_create_subscription_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="list_subscriptions",
            description="List configured subscriptions.",
            parameters={
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
            execute=_list_subscriptions_execute,
        ),
        ToolDefinition(
            name="get_subscription",
            description=(
                "Fetch a single subscription by id, returning its channel,"
                " status, frequency and match rules."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "UUID of the subscription to fetch.",
                    }
                },
                "required": ["subscription_id"],
            },
            execute=_get_subscription_execute,
        ),
        ToolDefinition(
            name="update_subscription",
            description=(
                "Partially update an EXISTING subscription by id. Only supplied"
                " fields change; the subscription must already exist (use"
                " create_subscription to add a new one). Call get_subscription /"
                " list_subscriptions first to confirm the id."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "UUID of the subscription to update.",
                    },
                    "name": {"type": "string"},
                    "channel_config": {"type": "object"},
                    "match_rules": {"type": "object"},
                    "frequency": {"type": "string"},
                    "quiet_hours": {"type": "object"},
                    "timezone": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused"],
                    },
                },
                "required": ["subscription_id"],
            },
            execute=_update_subscription_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="delete_subscription",
            description="Soft-delete (pause) a subscription by id.",
            parameters={
                "type": "object",
                "properties": {"subscription_id": {"type": "string"}},
                "required": ["subscription_id"],
            },
            execute=_delete_subscription_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="create_pipeline",
            description="Create or update a pipeline definition by name.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["strict", "flexible", "batch"],
                    },
                    "steps": {"type": "array", "items": {"type": "object"}},
                    "max_steps": {"type": "integer"},
                    "on_failure": {
                        "type": "string",
                        "enum": ["abort", "skip", "retry"],
                    },
                    "tools_allowed": {"type": "array", "items": {"type": "string"}},
                    "tools_denied": {"type": "array", "items": {"type": "string"}},
                    "system_prompt": {"type": "string"},
                },
                "required": ["name", "mode"],
            },
            execute=_create_pipeline_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="list_pipelines",
            description="List persisted pipeline definitions.",
            parameters={"type": "object", "properties": {}},
            execute=_list_pipelines_execute,
        ),
        ToolDefinition(
            name="update_pipeline",
            description=(
                "Partially update an EXISTING pipeline definition by name. Only"
                " the supplied fields change; the pipeline must already exist"
                " (use create_pipeline to add a new one). The name is the"
                " immutable identifier and cannot be renamed here."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the pipeline to update.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["strict", "flexible", "batch"],
                    },
                    "steps": {"type": "array", "items": {"type": "object"}},
                    "max_steps": {"type": "integer"},
                    "on_failure": {
                        "type": "string",
                        "enum": ["abort", "skip", "retry"],
                    },
                    "tools_allowed": {"type": "array", "items": {"type": "string"}},
                    "tools_denied": {"type": "array", "items": {"type": "string"}},
                    "system_prompt": {"type": "string"},
                    "max_tokens_budget": {"type": "integer"},
                    "agent_mode": {"type": "string"},
                    "tool_permissions": {"type": "object"},
                },
                "required": ["name"],
            },
            execute=_update_pipeline_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="delete_pipeline",
            description="Delete a pipeline definition by name.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            execute=_delete_pipeline_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="run_pipeline",
            description=(
                "Trigger a run of a persisted pipeline by name via the task queue."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the persisted pipeline to run.",
                    },
                    "params": {
                        "type": "object",
                        "description": "Optional runtime params passed to the run.",
                    },
                },
                "required": ["name"],
            },
            execute=_run_pipeline_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="get_task_status",
            description=(
                "Get the status of a pipeline run by its task_chain_id"
                " (e.g. the id returned by run_pipeline's run record)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_chain_id": {
                        "type": "string",
                        "description": "TaskChain UUID to poll.",
                    }
                },
                "required": ["task_chain_id"],
            },
            execute=_get_task_status_execute,
        ),
        ToolDefinition(
            name="create_template",
            description=(
                "Create or update a custom digest template by name. Reuses a"
                " built-in base_template's aggregation and supplies per-format"
                " Jinja source."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "base_template": {
                        "type": "string",
                        "description": (
                            "Built-in template to reuse aggregation from"
                            " (e.g. daily-brief, weekly-roundup, push-card)."
                        ),
                    },
                    "formats": {"type": "array", "items": {"type": "string"}},
                    "default_format": {"type": "string"},
                    "jinja_source": {
                        "type": "object",
                        "description": "Map of format -> Jinja source string.",
                    },
                    "aggregate_config": {"type": "object"},
                    "status": {"type": "string", "enum": ["active", "archived"]},
                },
                "required": ["name", "base_template", "formats", "default_format"],
            },
            execute=_create_template_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="list_templates",
            description="List custom digest templates.",
            parameters={
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
            execute=_list_templates_execute,
        ),
        ToolDefinition(
            name="get_template",
            description=(
                "Fetch a single custom digest template by name, returning its"
                " base_template, formats, default_format and status."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the custom template to fetch.",
                    }
                },
                "required": ["name"],
            },
            execute=_get_template_execute,
        ),
        ToolDefinition(
            name="update_template",
            description=(
                "Partially update an EXISTING custom digest template by name. Only"
                " supplied fields change; the template must already exist (use"
                " create_template to add a new one). The name is the immutable"
                " identifier and cannot be renamed here."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the template to update.",
                    },
                    "base_template": {"type": "string"},
                    "formats": {"type": "array", "items": {"type": "string"}},
                    "default_format": {"type": "string"},
                    "jinja_source": {
                        "type": "object",
                        "description": "Map of format -> Jinja source string.",
                    },
                    "aggregate_config": {"type": "object"},
                    "status": {"type": "string", "enum": ["active", "archived"]},
                },
                "required": ["name"],
            },
            execute=_update_template_execute,
            mutates_external_state=True,
        ),
        ToolDefinition(
            name="delete_template",
            description="Delete a custom digest template by name.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            execute=_delete_template_execute,
            mutates_external_state=True,
        ),
    ]
