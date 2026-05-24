"""Agent tool registry and pipeline config loader.

Provides AgentToolRegistry for registering tools that can be invoked
by AgentRunner, and load_pipeline_config for loading YAML pipelines.
"""

from __future__ import annotations

import enum
import importlib.util
import logging
import sys
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

from intellisource.agent.pipeline import PipelineConfig
from intellisource.pipeline.processors import tools as atomic_tools

_PIPELINES_DIR = Path(__file__).resolve().parents[4] / "config" / "pipelines"
_DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)


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
                logger.info(
                    "auto_discover: tool %r already registered; "
                    "manual registration wins over %s",
                    tool_def.name,
                    child,
                )
                continue
            self._tools[tool_def.name] = tool_def


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
    """Collect from source, persist RawContent rows, return ids for downstream steps."""
    if tool_deps is None or tool_deps.collector_registry is None:
        logger.warning("tool_deps not injected for collect, returning placeholder")
        return {
            "status": "degraded",
            "tool": "collect",
            "reason": "tool_deps not injected",
            "collected": [],
            "source_id": source_id,
        }

    source_config: dict[str, Any] = {}
    source_uuid: _uuid.UUID | None = None
    task_id_raw = kwargs.get("task_id") or kwargs.get("collect_task_id")
    collect_task_id: _uuid.UUID | None = None
    if task_id_raw:
        try:
            collect_task_id = _uuid.UUID(str(task_id_raw))
        except ValueError:
            collect_task_id = None

    if tool_deps.session_factory is not None and source_id:
        try:
            from intellisource.storage.models import Source  # noqa: PLC0415

            source_uuid = _uuid.UUID(source_id)
            async with tool_deps.session_factory() as session:
                source_row = await session.get(Source, source_uuid)
            if source_row is not None:
                if not source_type:
                    source_type = str(source_row.type or "")
                source_config = {
                    "url": source_row.url,
                    "source_id": source_id,
                    "source_type": source_type,
                    "proxy": source_row.proxy,
                    "rate_limit_qps": source_row.rate_limit_qps,
                    "rate_limit_concurrency": source_row.rate_limit_concurrency,
                    "metadata": source_row.metadata_,
                }
        except Exception as exc:
            logger.warning(
                "_collect_execute: failed to load Source for %s: %s",
                source_id,
                exc,
            )

    if not source_config:
        source_config = {
            "url": source_id,
            "source_id": source_id,
            "source_type": source_type,
        }
        if source_id:
            try:
                source_uuid = _uuid.UUID(source_id)
            except ValueError:
                source_uuid = None

    from intellisource.collector.base import RawContent as CollectedRawContent
    from intellisource.core.errors import CollectorError  # noqa: PLC0415

    try:
        collector = tool_deps.collector_registry.get(source_type)
    except CollectorError:
        return {
            "status": "degraded",
            "tool": "collect",
            "reason": f"unknown source_type: {source_type}",
            "collected": [],
            "source_id": source_id,
        }

    collected_items: list[CollectedRawContent] = await collector.collect(
        source_config=source_config, **kwargs
    )

    raw_content_ids: list[str] = []
    collected_summary: list[dict[str, Any]] = []

    if tool_deps.session_factory is not None and source_uuid is not None:
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        async with tool_deps.session_factory() as session:
            repo = ContentRepository(session=session)
            for item in collected_items:
                existing = await repo.get_raw_by_fingerprint(item.fingerprint)
                if existing is not None:
                    raw_content_ids.append(str(existing.id))
                    collected_summary.append(
                        {
                            "id": str(existing.id),
                            "title": existing.title,
                            "source_url": existing.source_url,
                            "duplicate": True,
                        }
                    )
                    continue
                raw = await repo.create_raw(
                    source_id=source_uuid,
                    source_url=item.source_url,
                    fingerprint=item.fingerprint,
                    title=item.title,
                    author=item.author,
                    body_html=item.body_html,
                    body_text=item.body_text,
                    published_at=item.published_at,
                    raw_metadata=dict(item.raw_metadata),
                    collect_task_id=collect_task_id,
                )
                raw_content_ids.append(str(raw.id))
                collected_summary.append(
                    {
                        "id": str(raw.id),
                        "title": raw.title,
                        "source_url": raw.source_url,
                        "duplicate": False,
                    }
                )
            await session.commit()
    else:
        for item in collected_items:
            collected_summary.append(
                {
                    "title": item.title,
                    "source_url": item.source_url,
                    "fingerprint": item.fingerprint,
                }
            )

    first_id = raw_content_ids[0] if raw_content_ids else None
    return {
        "status": "ok",
        "tool": "collect",
        "collected": collected_summary,
        "raw_content_ids": raw_content_ids,
        "content_id": first_id,
        "source_id": source_id,
        "source_type": source_type,
    }


async def _process_execute(
    content_id: str = "",
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Fetch RawContent, run PipelineEngine, persist ProcessedContent."""
    if tool_deps is None or tool_deps.pipeline_engine is None:
        logger.warning("tool_deps not injected for process, returning placeholder")
        return {
            "status": "degraded",
            "tool": "process",
            "reason": "tool_deps not injected",
            "content_id": content_id,
        }

    if tool_deps.session_factory is None:
        logger.warning(
            "session_factory not injected for process, returning placeholder"
        )
        return {
            "status": "degraded",
            "tool": "process",
            "reason": "session_factory not injected",
            "content_id": content_id,
        }

    from datetime import datetime, timezone  # noqa: PLC0415

    from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415
    from intellisource.storage.repositories.content import (  # noqa: PLC0415
        ContentRepository,
    )

    try:
        raw_id = _uuid.UUID(content_id)
    except ValueError:
        return {
            "status": "degraded",
            "tool": "process",
            "reason": f"invalid content_id: {content_id!r}",
            "content_id": content_id,
        }

    ctx = PipelineContext()
    ctx.set("content_id", content_id)

    async with tool_deps.session_factory() as session:
        repo = ContentRepository(session=session)
        raw = await repo.get_raw_by_id(raw_id)
        if raw is None:
            return {
                "status": "degraded",
                "tool": "process",
                "reason": f"RawContent not found: {content_id}",
                "content_id": content_id,
            }

        ctx.set("body_html", raw.body_html or "")
        ctx.set("body_text", raw.body_text or "")
        ctx.set("title", raw.title or "")
        ctx.set("fingerprint", raw.fingerprint or "")
        ctx.set("content_id", str(raw.id))

        ctx = tool_deps.pipeline_engine.execute(ctx)

        tags_val = ctx.get("tags")
        tags: list[str] = tags_val if isinstance(tags_val, list) else []

        existing_processed = await repo.get_processed_by_raw_id(raw_id)
        if existing_processed is not None:
            processed = existing_processed
        else:
            processed = await repo.create(
                raw_content_id=raw_id,
                title=str(ctx.get("title") or raw.title or ""),
                body_text=str(ctx.get("body_text") or raw.body_text or ""),
                tags=tags,
                fingerprint=str(ctx.get("fingerprint") or raw.fingerprint or ""),
                source_url=raw.source_url,
                processing_status="completed",
                processed_at=datetime.now(tz=timezone.utc),
            )

        raw.status = "processed"
        raw.processed_at = datetime.now(tz=timezone.utc)
        await session.commit()

    result: dict[str, Any] = {
        "body_html": ctx.get("body_html"),
        "body_text": ctx.get("body_text"),
        "title": ctx.get("title"),
        "fingerprint": ctx.get("fingerprint"),
        "content_id": str(processed.id),
        "raw_content_id": str(raw_id),
    }
    return {"status": "ok", "tool": "process", "result": result}


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
    logger.warning("tool_deps not injected for distribute, returning placeholder")
    return {
        "status": "degraded",
        "tool": "distribute",
        "reason": "tool_deps not injected",
        "content_id": content_id,
    }


async def _search_execute(
    query: str = "",
    top_k: int = 10,
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke HybridSearchEngine.search() with the given query."""
    if tool_deps is None:
        factory = None
        session_factory = None
    else:
        factory = getattr(tool_deps, "search_engine_factory", None)
        session_factory = getattr(tool_deps, "session_factory", None)
    if factory is not None and session_factory is not None:
        async with session_factory() as session:
            engine = factory(session)
            response = await engine.search(query=query, limit=top_k, **kwargs)
        return {
            "status": "ok",
            "tool": "search",
            "response": _serialize_search_response(response),
        }
    logger.warning("tool_deps not injected for search, returning placeholder")
    return {
        "status": "degraded",
        "tool": "search",
        "reason": "tool_deps not injected",
        "query": query,
    }


def _serialize_search_response(response: Any) -> dict[str, Any]:
    """Convert HybridSearchEngine SearchResponse to a JSON-friendly dict."""
    from dataclasses import asdict, is_dataclass

    if is_dataclass(response) and not isinstance(response, type):
        payload = asdict(response)
        items = payload.get("items") or []
        serialized_items: list[dict[str, Any]] = []
        for item in items:
            if is_dataclass(item) and not isinstance(item, type):
                row = asdict(item)
            elif isinstance(item, dict):
                row = dict(item)
            else:
                continue
            content_id = row.get("content_id")
            if content_id is not None:
                row["content_id"] = str(content_id)
            serialized_items.append(row)
        payload["items"] = serialized_items
        return payload
    if isinstance(response, dict):
        return response
    return {"items": [], "total": 0, "query_time_ms": 0}


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
            content = await repo.get_by_id(_uuid.UUID(content_id))
            return {
                "status": "ok",
                "tool": "get_content_detail",
                "content": content,
                "content_id": content_id,
            }
    logger.warning(
        "tool_deps not injected for get_content_detail, returning placeholder"
    )
    return {
        "status": "degraded",
        "tool": "get_content_detail",
        "reason": "tool_deps not injected",
        "content_id": content_id,
    }


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
    logger.warning(
        "tool_deps not injected for summarize_for_user, returning placeholder"
    )
    return {
        "status": "degraded",
        "tool": "summarize_for_user",
        "reason": "tool_deps not injected",
        "content_id": content_id,
    }


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
        logger.warning("tool_deps not injected for llm_complete, returning placeholder")
        return {
            "status": "degraded",
            "tool": "llm_complete",
            "reason": "tool_deps not injected",
            "call_type": call_type,
        }
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
                    "channels": {"type": "string"},
                    "content_id": {"type": "string"},
                },
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
