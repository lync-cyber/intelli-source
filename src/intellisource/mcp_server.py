"""MCP server exposing IntelliSource control-plane capabilities.

A thin Model Context Protocol adapter over the *same* domain services the REST
API and the agent tools use — ``PipelineDefinitionService`` /
``SourceConfigService`` / ``SubscriptionService`` / ``TemplateService`` plus the
read-only ``HybridSearchEngine`` and the content / task-chain repositories — so
the three transports stay behaviourally identical and logic lives only in the
services (north star).

Run as a stdio MCP server::

    python -m intellisource.mcp_server
    intellisource-mcp            # via the console_script entry point
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.config.models import SourceConfig
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.template_models import TemplateConfig, TemplateValidationError
from intellisource.observability.logging import get_logger
from intellisource.pipeline.definition_service import PipelineDefinitionService
from intellisource.search.hybrid import HybridSearchEngine
from intellisource.source.service import SourceConfigService
from intellisource.storage.repositories.content import ContentRepository
from intellisource.storage.repositories.task_chain import TaskChainRepository
from intellisource.subscription.service import SubscriptionService
from intellisource.template.service import TemplateService

logger = get_logger(__name__)

# A session factory is a zero-arg callable returning an async context manager
# that yields an AsyncSession (e.g. ``DatabaseManager.get_session``).
SessionFactory = Callable[[], Any]
SearchEngineFactory = Callable[[AsyncSession], Any]

_db_manager: Any = None


def _default_session_factory() -> Any:
    """Lazily build a process-wide DatabaseManager-backed session context."""
    global _db_manager
    if _db_manager is None:
        from intellisource.storage.database import DatabaseManager

        _db_manager = DatabaseManager()
    return _db_manager.get_session()


def _default_search_engine_factory(session: AsyncSession) -> HybridSearchEngine:
    return HybridSearchEngine(session)


def _pipeline_dict(cfg: PipelineConfig) -> dict[str, Any]:
    return {
        "name": cfg.name,
        "mode": cfg.mode,
        "max_steps": cfg.max_steps,
        "on_failure": cfg.on_failure,
        "steps": cfg.steps,
        "tools_allowed": cfg.tools_allowed,
        "tools_denied": cfg.tools_denied,
        "system_prompt": cfg.system_prompt,
    }


def _source_dict(s: Any) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "type": s.type,
        "url": s.url,
        "status": s.status,
        "tags": list(getattr(s, "tags", None) or []),
        "discipline_tags": list(getattr(s, "discipline_tags", None) or []),
        "schedule_interval": getattr(s, "schedule_interval", None),
    }


def _subscription_dict(s: Any) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "channel": s.channel,
        "status": s.status,
        "frequency": getattr(s, "frequency", None),
        "match_rules": dict(getattr(s, "match_rules", None) or {}),
    }


def _search_response_dict(response: Any) -> dict[str, Any]:
    from dataclasses import asdict, is_dataclass

    if is_dataclass(response) and not isinstance(response, type):
        payload = asdict(response)
        items = []
        for item in payload.get("items") or []:
            row = dict(item) if isinstance(item, dict) else item
            cid = row.get("content_id") if isinstance(row, dict) else None
            if isinstance(row, dict) and cid is not None:
                row["content_id"] = str(cid)
            items.append(row)
        payload["items"] = items
        return payload
    if isinstance(response, dict):
        return response
    return {"items": [], "total": 0, "query_time_ms": 0}


def _only_set(**maybe: Any) -> dict[str, Any]:
    """Return only the keyword args that were supplied a non-None value.

    Lets a patch tool accept every editable field as an optional parameter and
    forward exactly the ones the caller set, so an unspecified field is left
    untouched rather than reset to a default.
    """
    return {k: v for k, v in maybe.items() if v is not None}


def build_mcp_server(
    session_factory: SessionFactory | None = None,
    *,
    search_engine_factory: SearchEngineFactory | None = None,
) -> FastMCP:
    """Build a FastMCP server whose tools delegate to the domain services."""
    mcp = FastMCP("intellisource")
    session_cm: SessionFactory = session_factory or _default_session_factory
    search_factory: SearchEngineFactory = (
        search_engine_factory or _default_search_engine_factory
    )

    # -- pipelines ----------------------------------------------------------

    @mcp.tool(
        name="list_pipelines",
        description=(
            "List every persisted pipeline definition. No parameters. Returns a"
            " list of summaries (name, mode, max_steps, tools_allowed). Call this"
            " before get_pipeline / update_pipeline to discover available names."
        ),
    )
    async def list_pipelines() -> list[dict[str, Any]]:
        async with session_cm() as session:
            return await PipelineDefinitionService(session).list_summaries()

    @mcp.tool(
        name="get_pipeline",
        description=(
            "Fetch one pipeline definition. Params: name (str). Returns the full"
            " config (mode, steps, max_steps, on_failure, tools_allowed,"
            " tools_denied, system_prompt) or {error:'not_found'} when absent."
        ),
    )
    async def get_pipeline(name: str) -> dict[str, Any]:
        async with session_cm() as session:
            cfg = await PipelineDefinitionService(session).get(name)
        if cfg is None:
            return {"error": "not_found", "name": name}
        return _pipeline_dict(cfg)

    @mcp.tool(
        name="create_pipeline",
        description=(
            "Create or replace a pipeline definition (upsert by name). Params:"
            " name, mode (strict/flexible/batch), steps (array of step objects),"
            " max_steps, on_failure, tools_allowed, system_prompt. Returns the"
            " persisted config. Use update_pipeline to edit an existing one"
            " without resetting unspecified fields."
        ),
    )
    async def create_pipeline(
        name: str,
        mode: str = "flexible",
        steps: list[dict[str, Any]] | None = None,
        max_steps: int = 50,
        on_failure: str = "abort",
        tools_allowed: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "mode": mode,
            "steps": steps or [],
            "max_steps": max_steps,
            "on_failure": on_failure,
        }
        if tools_allowed is not None:
            payload["tools_allowed"] = tools_allowed
        if system_prompt is not None:
            payload["system_prompt"] = system_prompt
        try:
            cfg = PipelineConfig.from_dict(payload)
        except Exception as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        async with session_cm() as session:
            created = await PipelineDefinitionService(session).create(cfg)
            await session.commit()
        return _pipeline_dict(created)

    @mcp.tool(
        name="update_pipeline",
        description=(
            "Partially update an EXISTING pipeline definition by name. Params:"
            " name (required) plus any of mode, steps, max_steps, on_failure,"
            " tools_allowed, tools_denied, system_prompt, max_tokens_budget,"
            " agent_mode, tool_permissions — only the ones you pass change."
            " Returns the updated config, or {error:'not_found'} when the name"
            " does not exist (use create_pipeline to add a new one)."
        ),
    )
    async def update_pipeline(
        name: str,
        mode: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        max_steps: int | None = None,
        on_failure: str | None = None,
        tools_allowed: list[str] | None = None,
        tools_denied: list[str] | None = None,
        system_prompt: str | None = None,
        max_tokens_budget: int | None = None,
        agent_mode: str | None = None,
        tool_permissions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fields = _only_set(
            mode=mode,
            steps=steps,
            max_steps=max_steps,
            on_failure=on_failure,
            tools_allowed=tools_allowed,
            tools_denied=tools_denied,
            system_prompt=system_prompt,
            max_tokens_budget=max_tokens_budget,
            agent_mode=agent_mode,
            tool_permissions=tool_permissions,
        )
        if not fields:
            return {"error": "invalid_input", "reason": "no fields to update"}
        try:
            async with session_cm() as session:
                updated = await PipelineDefinitionService(session).update(name, fields)
                if updated is None:
                    return {"error": "not_found", "name": name}
                payload = _pipeline_dict(updated)
                await session.commit()
        except Exception as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        return payload

    @mcp.tool(
        name="delete_pipeline",
        description=(
            "Delete a pipeline definition by name. Params: name (str). Returns"
            " {deleted: bool, name}. Idempotent: deleting an absent name returns"
            " deleted=false rather than erroring."
        ),
    )
    async def delete_pipeline(name: str) -> dict[str, Any]:
        async with session_cm() as session:
            deleted = await PipelineDefinitionService(session).delete(name)
            await session.commit()
        return {"deleted": deleted, "name": name}

    # -- sources ------------------------------------------------------------

    @mcp.tool(
        name="list_sources",
        description=(
            "List configured data sources. Params: limit (int, capped at 100)."
            " Returns a list of {id, name, type, url, status}. Use the id with"
            " get_source / update_source / delete_source."
        ),
    )
    async def list_sources(limit: int = 20) -> list[dict[str, Any]]:
        async with session_cm() as session:
            result = await SourceConfigService(session).list_paginated(
                limit=min(limit, 100)
            )
            return [_source_dict(s) for s in result["items"]]

    @mcp.tool(
        name="get_source",
        description=(
            "Fetch one data source by id. Params: source_id (UUID str). Returns"
            " the full source (id, name, type, url, status, tags,"
            " discipline_tags, schedule_interval) or {error:'not_found'}."
        ),
    )
    async def get_source(source_id: str) -> dict[str, Any]:
        try:
            sid = _uuid.UUID(source_id)
        except ValueError:
            return {"error": "invalid_input", "reason": f"bad source_id: {source_id!r}"}
        async with session_cm() as session:
            row = await SourceConfigService(session).get(sid)
        if row is None:
            return {"error": "not_found", "source_id": source_id}
        return _source_dict(row)

    @mcp.tool(
        name="create_source",
        description=(
            "Create or replace a data source (upsert by name). Params: name, type"
            " (rss/api/web), url, tags (optional). Returns {id, name, type,"
            " status}, or {error:'invalid_input'} when the url/type is malformed."
        ),
    )
    async def create_source(
        name: str, type: str, url: str, tags: list[str] | None = None
    ) -> dict[str, Any]:
        try:
            cfg = SourceConfig.model_validate(
                {"name": name, "type": type, "url": url, "tags": tags or []}
            )
        except Exception as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        async with session_cm() as session:
            created = await SourceConfigService(session).create(cfg)
            payload = {
                "id": str(created.id),
                "name": created.name,
                "type": created.type,
                "status": created.status,
            }
            await session.commit()
        return payload

    @mcp.tool(
        name="update_source",
        description=(
            "Partially update an EXISTING data source by id. Params: source_id"
            " (required) plus any of name, url, tags, discipline_tags,"
            " schedule_interval, status (active/paused) — only the ones you pass"
            " change. Returns the updated source, or {error:'not_found'} when the"
            " id is absent (use create_source to add a new one)."
        ),
    )
    async def update_source(
        source_id: str,
        name: str | None = None,
        url: str | None = None,
        tags: list[str] | None = None,
        discipline_tags: list[str] | None = None,
        schedule_interval: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        try:
            sid = _uuid.UUID(source_id)
        except ValueError:
            return {"error": "invalid_input", "reason": f"bad source_id: {source_id!r}"}
        fields = _only_set(
            name=name,
            url=url,
            tags=tags,
            discipline_tags=discipline_tags,
            schedule_interval=schedule_interval,
            status=status,
        )
        if not fields:
            return {"error": "invalid_input", "reason": "no fields to update"}
        async with session_cm() as session:
            updated = await SourceConfigService(session).patch(sid, fields)
            if updated is None:
                return {"error": "not_found", "source_id": source_id}
            payload = _source_dict(updated)
            await session.commit()
        return payload

    @mcp.tool(
        name="delete_source",
        description=(
            "Soft-delete (pause) a data source by id. Params: source_id (UUID"
            " str). Returns {deleted: bool, source_id}. Soft delete preserves the"
            " row's collected-content history; deleted=false means the id was"
            " absent."
        ),
    )
    async def delete_source(source_id: str) -> dict[str, Any]:
        try:
            sid = _uuid.UUID(source_id)
        except ValueError:
            return {"error": "invalid_input", "reason": f"bad source_id: {source_id!r}"}
        async with session_cm() as session:
            deleted = await SourceConfigService(session).delete(sid)
            await session.commit()
        return {"deleted": deleted, "source_id": source_id}

    # -- subscriptions ------------------------------------------------------

    @mcp.tool(
        name="list_subscriptions",
        description=(
            "List configured subscriptions. Params: limit (int, capped at 100)."
            " Returns a list of {id, name, channel, status}. Use the id with"
            " get_subscription / update_subscription / delete_subscription."
        ),
    )
    async def list_subscriptions(limit: int = 20) -> list[dict[str, Any]]:
        async with session_cm() as session:
            result = await SubscriptionService(session).list_paginated(
                limit=min(limit, 100)
            )
            return [_subscription_dict(s) for s in result["items"]]

    @mcp.tool(
        name="get_subscription",
        description=(
            "Fetch one subscription by id. Params: subscription_id (UUID str)."
            " Returns the subscription (id, name, channel, status, frequency,"
            " match_rules) or {error:'not_found'} when absent."
        ),
    )
    async def get_subscription(subscription_id: str) -> dict[str, Any]:
        try:
            sid = _uuid.UUID(subscription_id)
        except ValueError:
            return {"error": "invalid_input", "reason": f"bad id: {subscription_id!r}"}
        async with session_cm() as session:
            row = await SubscriptionService(session).get(sid)
        if row is None:
            return {"error": "not_found", "subscription_id": subscription_id}
        return _subscription_dict(row)

    @mcp.tool(
        name="create_subscription",
        description=(
            "Create a subscription on a channel. Params: name, channel"
            " (email/wechat/wework), channel_config (e.g. {to_addr} for email),"
            " match_rules, frequency. Returns {id, name, channel, status}, or"
            " {error:'invalid_input'} when channel rules are unmet (email needs"
            " a valid to_addr)."
        ),
    )
    async def create_subscription(
        name: str,
        channel: str,
        channel_config: dict[str, Any] | None = None,
        match_rules: dict[str, Any] | None = None,
        frequency: str = "realtime",
    ) -> dict[str, Any]:
        try:
            cfg = SubscriptionConfig.model_validate(
                {
                    "name": name,
                    "channel": channel,
                    "channel_config": channel_config or {},
                    "match_rules": match_rules or {},
                    "frequency": frequency,
                }
            )
        except Exception as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        try:
            async with session_cm() as session:
                created = await SubscriptionService(session).create(cfg)
                payload = {
                    "id": str(created.id),
                    "name": created.name,
                    "channel": created.channel,
                    "status": created.status,
                }
                await session.commit()
        except Exception as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        return payload

    @mcp.tool(
        name="update_subscription",
        description=(
            "Partially update an EXISTING subscription by id. Params:"
            " subscription_id (required) plus any of name, channel_config,"
            " match_rules, frequency, quiet_hours, timezone, status — only the"
            " ones you pass change. Returns the updated subscription, or"
            " {error:'not_found'} when the id is absent."
        ),
    )
    async def update_subscription(
        subscription_id: str,
        name: str | None = None,
        channel_config: dict[str, Any] | None = None,
        match_rules: dict[str, Any] | None = None,
        frequency: str | None = None,
        quiet_hours: dict[str, Any] | None = None,
        timezone: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        try:
            sid = _uuid.UUID(subscription_id)
        except ValueError:
            return {"error": "invalid_input", "reason": f"bad id: {subscription_id!r}"}
        fields = _only_set(
            name=name,
            channel_config=channel_config,
            match_rules=match_rules,
            frequency=frequency,
            quiet_hours=quiet_hours,
            timezone=timezone,
            status=status,
        )
        if not fields:
            return {"error": "invalid_input", "reason": "no fields to update"}
        async with session_cm() as session:
            updated = await SubscriptionService(session).patch(sid, fields)
            if updated is None:
                return {"error": "not_found", "subscription_id": subscription_id}
            payload = _subscription_dict(updated)
            await session.commit()
        return payload

    @mcp.tool(
        name="delete_subscription",
        description=(
            "Soft-delete (pause) a subscription by id. Params: subscription_id"
            " (UUID str). Returns {deleted: bool, subscription_id}. Soft delete"
            " preserves push-record history; deleted=false means the id was"
            " absent."
        ),
    )
    async def delete_subscription(subscription_id: str) -> dict[str, Any]:
        try:
            sid = _uuid.UUID(subscription_id)
        except ValueError:
            return {"error": "invalid_input", "reason": f"bad id: {subscription_id!r}"}
        async with session_cm() as session:
            deleted = await SubscriptionService(session).delete(sid)
            await session.commit()
        return {"deleted": deleted, "subscription_id": subscription_id}

    # -- run / status / search / content ------------------------------------

    @mcp.tool(
        name="trigger_pipeline",
        description=(
            "Dispatch a run of a persisted pipeline via the task queue. Params:"
            " name, params (optional run kwargs). Returns {task_id} (the Celery"
            " id), or {error} when the name is unknown or the broker is"
            " unreachable. Poll progress with get_task_status."
        ),
    )
    async def trigger_pipeline(
        name: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async with session_cm() as session:
            exists = await PipelineDefinitionService(session).get(name)
        if exists is None:
            return {"error": "not_found", "name": name}
        from intellisource.scheduler.celery_app import celery_app
        from intellisource.scheduler.dispatch import send_task_with_trace

        try:
            result = send_task_with_trace(
                "run_pipeline",
                kwargs={"pipeline_name": name, "params": params or {}},
                celery_instance=celery_app,
            )
        except Exception as exc:
            return {"error": "dispatch_failed", "reason": str(exc)}
        return {"task_id": str(getattr(result, "id", result))}

    @mcp.tool(
        name="get_task_status",
        description=(
            "Read the status of a pipeline run by its task_chain_id. Params:"
            " task_chain_id (UUID str). Returns {task_chain_id, status,"
            " completed_steps, total_steps, error_message} or"
            " {error:'not_found'}. Read-only; safe to poll."
        ),
    )
    async def get_task_status(task_chain_id: str) -> dict[str, Any]:
        async with session_cm() as session:
            chain = await TaskChainRepository(session).get(task_chain_id)
        if chain is None:
            return {"error": "not_found", "task_chain_id": task_chain_id}
        return {
            "task_chain_id": str(chain.id),
            "status": chain.status,
            "completed_steps": chain.completed_steps,
            "total_steps": chain.total_steps,
            "error_message": chain.error_message,
        }

    @mcp.tool(
        name="search",
        description=(
            "Search the knowledge base (hybrid keyword + semantic). Params: query"
            " (non-empty str), top_k (int). Returns {items:[{content_id, title,"
            " snippet, score, source_name, published_at}], total, query_time_ms},"
            " or {error:'invalid_input'} for an empty query. Read-only."
        ),
    )
    async def search(query: str, top_k: int = 10) -> dict[str, Any]:
        if not query:
            return {"error": "invalid_input", "reason": "query must not be empty"}
        try:
            async with session_cm() as session:
                engine = search_factory(session)
                response = await engine.search(query=query, limit=top_k)
        except ValueError as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        except Exception as exc:
            logger.warning("mcp search failed: %s", exc)
            return {"error": "error", "reason": str(exc)}
        return _search_response_dict(response)

    @mcp.tool(
        name="get_content_detail",
        description=(
            "Fetch one processed content row by id. Params: content_id (UUID"
            " str). Returns {id, title, summary, tags, source_name, source_url,"
            " published_at, processing_status} or {error:'not_found'}. Read-only."
        ),
    )
    async def get_content_detail(content_id: str) -> dict[str, Any]:
        try:
            cid = _uuid.UUID(content_id)
        except ValueError:
            return {
                "error": "invalid_input",
                "reason": f"bad content_id: {content_id!r}",
            }
        async with session_cm() as session:
            row = await ContentRepository(session).get_by_id(cid)
        if row is None:
            return {"error": "not_found", "content_id": content_id}
        return {
            "id": str(row.id),
            "title": row.title,
            "summary": row.summary,
            "tags": list(row.tags or []),
            "source_name": row.source_name,
            "source_url": row.source_url,
            "published_at": (
                row.published_at.isoformat() if row.published_at else None
            ),
            "processing_status": row.processing_status,
        }

    # -- templates ----------------------------------------------------------

    @mcp.tool(
        name="list_templates",
        description=(
            "List custom digest templates. Params: limit (int, capped at 100)."
            " Returns a list of {name, base_template, default_format, status}."
        ),
    )
    async def list_templates(limit: int = 20) -> list[dict[str, Any]]:
        async with session_cm() as session:
            result = await TemplateService(session).list_paginated(
                limit=min(limit, 100)
            )
            return [
                {
                    "name": t.name,
                    "base_template": t.base_template,
                    "default_format": t.default_format,
                    "status": t.status,
                }
                for t in result["items"]
            ]

    @mcp.tool(
        name="get_template",
        description=(
            "Fetch one custom digest template by name. Params: name (str)."
            " Returns the full template (base_template, formats, default_format,"
            " jinja_source, aggregate_config, status) or {error:'not_found'}."
        ),
    )
    async def get_template(name: str) -> dict[str, Any]:
        async with session_cm() as session:
            row = await TemplateService(session).get_by_name(name)
        if row is None:
            return {"error": "not_found", "name": name}
        return {
            "name": row.name,
            "base_template": row.base_template,
            "formats": list(row.formats),
            "default_format": row.default_format,
            "jinja_source": dict(row.jinja_source),
            "aggregate_config": dict(row.aggregate_config),
            "status": row.status,
        }

    @mcp.tool(
        name="create_template",
        description=(
            "Create or replace a custom digest template (upsert by name). Params:"
            " name, base_template (a built-in to reuse aggregation from),"
            " formats, default_format, jinja_source (format->Jinja string),"
            " aggregate_config. Returns {name, base_template, status}, or"
            " {error:'invalid_input'} when base_template is unknown or the"
            " formats/default_format are inconsistent."
        ),
    )
    async def create_template(
        name: str,
        base_template: str,
        formats: list[str],
        default_format: str,
        jinja_source: dict[str, str] | None = None,
        aggregate_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            cfg = TemplateConfig(
                name=name,
                base_template=base_template,
                formats=formats,
                default_format=default_format,
                jinja_source=jinja_source or {},
                aggregate_config=aggregate_config or {},
            )
        except Exception as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        try:
            async with session_cm() as session:
                created = await TemplateService(session).create(cfg)
                payload = {
                    "name": created.name,
                    "base_template": created.base_template,
                    "status": created.status,
                }
                await session.commit()
        except TemplateValidationError as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        return payload

    @mcp.tool(
        name="update_template",
        description=(
            "Partially update an EXISTING custom digest template by name. Params:"
            " name (required) plus any of base_template, formats, default_format,"
            " jinja_source, aggregate_config, status — only the ones you pass"
            " change. Returns {name, base_template, status}, or"
            " {error:'not_found'} when the name is absent (use create_template to"
            " add a new one)."
        ),
    )
    async def update_template(
        name: str,
        base_template: str | None = None,
        formats: list[str] | None = None,
        default_format: str | None = None,
        jinja_source: dict[str, str] | None = None,
        aggregate_config: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        fields = _only_set(
            base_template=base_template,
            formats=formats,
            default_format=default_format,
            jinja_source=jinja_source,
            aggregate_config=aggregate_config,
            status=status,
        )
        if not fields:
            return {"error": "invalid_input", "reason": "no fields to update"}
        try:
            async with session_cm() as session:
                service = TemplateService(session)
                row = await service.get_by_name(name)
                if row is None:
                    return {"error": "not_found", "name": name}
                updated = await service.patch(row.id, fields)
                payload = {
                    "name": updated.name,  # type: ignore[union-attr]
                    "base_template": updated.base_template,  # type: ignore[union-attr]
                    "status": updated.status,  # type: ignore[union-attr]
                }
                await session.commit()
        except TemplateValidationError as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        return payload

    @mcp.tool(
        name="delete_template",
        description=(
            "Delete a custom digest template by name. Params: name (str)."
            " Returns {deleted: bool, name}. deleted=false means the name was"
            " absent (built-in templates are not deletable here)."
        ),
    )
    async def delete_template(name: str) -> dict[str, Any]:
        async with session_cm() as session:
            service = TemplateService(session)
            row = await service.get_by_name(name)
            if row is None:
                return {"deleted": False, "name": name}
            await service.delete(row.id)
            await session.commit()
        return {"deleted": True, "name": name}

    return mcp


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    build_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
