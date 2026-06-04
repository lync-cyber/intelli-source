"""MCP server exposing IntelliSource control-plane capabilities.

A thin Model Context Protocol adapter over the *same* domain services the REST
API and the agent tools use — ``PipelineDefinitionService`` /
``SourceConfigService`` / ``SubscriptionService`` — so the three transports stay
behaviourally identical and logic lives only in the services (north star).

Run as a stdio MCP server::

    python -m intellisource.mcp_server
"""

from __future__ import annotations

from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from intellisource.config.models import SourceConfig
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.config.template_models import TemplateConfig, TemplateValidationError
from intellisource.observability.logging import get_logger
from intellisource.pipeline.definition_service import PipelineDefinitionService
from intellisource.source.service import SourceConfigService
from intellisource.subscription.service import SubscriptionService
from intellisource.template.service import TemplateService

logger = get_logger(__name__)

# A session factory is a zero-arg callable returning an async context manager
# that yields an AsyncSession (e.g. ``DatabaseManager.get_session``).
SessionFactory = Callable[[], Any]

_db_manager: Any = None


def _default_session_factory() -> Any:
    """Lazily build a process-wide DatabaseManager-backed session context."""
    global _db_manager
    if _db_manager is None:
        from intellisource.storage.database import DatabaseManager

        _db_manager = DatabaseManager()
    return _db_manager.get_session()


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


def build_mcp_server(session_factory: SessionFactory | None = None) -> FastMCP:
    """Build a FastMCP server whose tools delegate to the domain services."""
    mcp = FastMCP("intellisource")
    session_cm: SessionFactory = session_factory or _default_session_factory

    @mcp.tool(name="list_pipelines", description="List persisted pipeline definitions.")
    async def list_pipelines() -> list[dict[str, Any]]:
        async with session_cm() as session:
            return await PipelineDefinitionService(session).list_summaries()

    @mcp.tool(name="get_pipeline", description="Get a pipeline definition by name.")
    async def get_pipeline(name: str) -> dict[str, Any]:
        async with session_cm() as session:
            cfg = await PipelineDefinitionService(session).get(name)
        if cfg is None:
            return {"error": "not_found", "name": name}
        return _pipeline_dict(cfg)

    @mcp.tool(
        name="create_pipeline",
        description="Create or replace a pipeline definition (upsert by name).",
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
        name="delete_pipeline", description="Delete a pipeline definition by name."
    )
    async def delete_pipeline(name: str) -> dict[str, Any]:
        async with session_cm() as session:
            deleted = await PipelineDefinitionService(session).delete(name)
            await session.commit()
        return {"deleted": deleted, "name": name}

    @mcp.tool(name="list_sources", description="List configured data sources.")
    async def list_sources(limit: int = 20) -> list[dict[str, Any]]:
        async with session_cm() as session:
            result = await SourceConfigService(session).list_paginated(
                limit=min(limit, 100)
            )
            return [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "type": s.type,
                    "url": s.url,
                    "status": s.status,
                }
                for s in result["items"]
            ]

    @mcp.tool(
        name="create_source",
        description="Create or replace a data source (rss/api/web).",
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

    @mcp.tool(name="list_subscriptions", description="List configured subscriptions.")
    async def list_subscriptions(limit: int = 20) -> list[dict[str, Any]]:
        async with session_cm() as session:
            result = await SubscriptionService(session).list_paginated(
                limit=min(limit, 100)
            )
            return [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "channel": s.channel,
                    "status": s.status,
                }
                for s in result["items"]
            ]

    @mcp.tool(
        name="trigger_pipeline",
        description="Dispatch a run of the named pipeline via the task queue.",
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

    @mcp.tool(name="list_templates", description="List custom digest templates.")
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

    @mcp.tool(name="get_template", description="Get a custom digest template by name.")
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
        description="Create or replace a custom digest template (upsert by name).",
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
        name="delete_template", description="Delete a custom digest template by name."
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
