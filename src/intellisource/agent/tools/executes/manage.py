"""Management (CRUD) tool execute functions: sources / subscriptions / pipelines.

Exposes the control-plane domain services to the agent so an LLM can provision
and inspect sources, subscriptions and pipeline definitions. The services are
injected via ``ToolDeps`` factories (constructed in the composition root); this
module imports only the cross-cutting config value objects, never a domain
service package, so the agent layer gains no static edge to those services.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from intellisource.agent.tools.results import tool_error, tool_ok
from intellisource.config.models import SourceConfig
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.template_models import TemplateConfig, TemplateValidationError
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

_SOURCE_FIELDS = (
    "name",
    "type",
    "url",
    "tags",
    "discipline_tags",
    "schedule_interval",
    "schedule_adaptive",
    "proxy",
    "rate_limit_qps",
    "rate_limit_concurrency",
    "metadata",
)
_SUB_FIELDS = (
    "name",
    "channel",
    "channel_config",
    "match_rules",
    "frequency",
    "quiet_hours",
    "timezone",
    "discipline_tags",
)
_PIPELINE_FIELDS = (
    "name",
    "mode",
    "steps",
    "max_steps",
    "on_failure",
    "tools_allowed",
    "tools_denied",
    "system_prompt",
    "max_tokens_budget",
    "agent_mode",
    "tool_permissions",
)
_TEMPLATE_FIELDS = (
    "name",
    "base_template",
    "formats",
    "default_format",
    "jinja_source",
    "aggregate_config",
    "status",
)


def _pick(kwargs: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {k: kwargs[k] for k in fields if k in kwargs}


def _wiring(tool_deps: Any, factory_attr: str) -> tuple[Any, Any]:
    """Return (service_factory, session_factory) or (None, None) when unwired."""
    if tool_deps is None:
        return None, None
    return getattr(tool_deps, factory_attr, None), getattr(
        tool_deps, "session_factory", None
    )


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


async def _create_source_execute(
    tool_deps: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Create (idempotent upsert) a source from LLM-supplied fields."""
    factory, session_factory = _wiring(tool_deps, "source_service_factory")
    if factory is None or session_factory is None:
        return tool_error("create_source", "tool_deps not injected", code="not_wired")
    try:
        cfg = SourceConfig(**_pick(kwargs, _SOURCE_FIELDS))
    except Exception as exc:
        return tool_error("create_source", str(exc), code="invalid_input")
    try:
        async with session_factory() as session:
            created = await factory(session).create(cfg)
            payload = {
                "id": str(created.id),
                "name": created.name,
                "type": created.type,
                "status": created.status,
            }
            await session.commit()
        return tool_ok("create_source", source=payload)
    except Exception as exc:
        logger.warning("create_source failed: %s", exc)
        return tool_error("create_source", str(exc), code="error")


async def _list_sources_execute(
    tool_deps: Any = None, limit: int = 20, **kwargs: Any
) -> dict[str, Any]:
    """List sources (id / name / type / url / status)."""
    factory, session_factory = _wiring(tool_deps, "source_service_factory")
    if factory is None or session_factory is None:
        return tool_error("list_sources", "tool_deps not injected", code="not_wired")
    try:
        async with session_factory() as session:
            result = await factory(session).list_paginated(limit=min(int(limit), 100))
            items = [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "type": s.type,
                    "url": s.url,
                    "status": s.status,
                }
                for s in result["items"]
            ]
        return tool_ok("list_sources", items=items, count=len(items))
    except Exception as exc:
        logger.warning("list_sources failed: %s", exc)
        return tool_error("list_sources", str(exc), code="error")


async def _delete_source_execute(
    tool_deps: Any = None, source_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Soft-delete a source by id (status='paused')."""
    factory, session_factory = _wiring(tool_deps, "source_service_factory")
    if factory is None or session_factory is None:
        return tool_error("delete_source", "tool_deps not injected", code="not_wired")
    try:
        sid = _uuid.UUID(str(source_id))
    except ValueError:
        return tool_error(
            "delete_source", f"invalid source_id: {source_id!r}", code="invalid_input"
        )
    try:
        async with session_factory() as session:
            deleted = await factory(session).delete(sid)
            await session.commit()
        if not deleted:
            return tool_error("delete_source", "source not found", code="not_found")
        return tool_ok("delete_source", source_id=str(sid))
    except Exception as exc:
        logger.warning("delete_source failed: %s", exc)
        return tool_error("delete_source", str(exc), code="error")


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


async def _create_subscription_execute(
    tool_deps: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Create a subscription from LLM-supplied fields."""
    factory, session_factory = _wiring(tool_deps, "subscription_service_factory")
    if factory is None or session_factory is None:
        return tool_error(
            "create_subscription", "tool_deps not injected", code="not_wired"
        )
    try:
        cfg = SubscriptionConfig(**_pick(kwargs, _SUB_FIELDS))
    except Exception as exc:
        return tool_error("create_subscription", str(exc), code="invalid_input")
    try:
        async with session_factory() as session:
            created = await factory(session).create(cfg)
            payload = {
                "id": str(created.id),
                "name": created.name,
                "channel": created.channel,
                "status": created.status,
            }
            await session.commit()
        return tool_ok("create_subscription", subscription=payload)
    except Exception as exc:
        logger.warning("create_subscription failed: %s", exc)
        return tool_error("create_subscription", str(exc), code="error")


async def _list_subscriptions_execute(
    tool_deps: Any = None, limit: int = 20, **kwargs: Any
) -> dict[str, Any]:
    """List subscriptions (id / name / channel / status)."""
    factory, session_factory = _wiring(tool_deps, "subscription_service_factory")
    if factory is None or session_factory is None:
        return tool_error(
            "list_subscriptions", "tool_deps not injected", code="not_wired"
        )
    try:
        async with session_factory() as session:
            result = await factory(session).list_paginated(limit=min(int(limit), 100))
            items = [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "channel": s.channel,
                    "status": s.status,
                }
                for s in result["items"]
            ]
        return tool_ok("list_subscriptions", items=items, count=len(items))
    except Exception as exc:
        logger.warning("list_subscriptions failed: %s", exc)
        return tool_error("list_subscriptions", str(exc), code="error")


async def _delete_subscription_execute(
    tool_deps: Any = None, subscription_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Soft-delete a subscription by id (status='paused')."""
    factory, session_factory = _wiring(tool_deps, "subscription_service_factory")
    if factory is None or session_factory is None:
        return tool_error(
            "delete_subscription", "tool_deps not injected", code="not_wired"
        )
    try:
        sid = _uuid.UUID(str(subscription_id))
    except ValueError:
        return tool_error(
            "delete_subscription",
            f"invalid subscription_id: {subscription_id!r}",
            code="invalid_input",
        )
    try:
        async with session_factory() as session:
            deleted = await factory(session).delete(sid)
            await session.commit()
        if not deleted:
            return tool_error(
                "delete_subscription", "subscription not found", code="not_found"
            )
        return tool_ok("delete_subscription", subscription_id=str(sid))
    except Exception as exc:
        logger.warning("delete_subscription failed: %s", exc)
        return tool_error("delete_subscription", str(exc), code="error")


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------


async def _create_pipeline_execute(
    tool_deps: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Create (idempotent upsert) a pipeline definition from LLM-supplied fields."""
    factory, session_factory = _wiring(tool_deps, "pipeline_service_factory")
    if factory is None or session_factory is None:
        return tool_error("create_pipeline", "tool_deps not injected", code="not_wired")
    payload = _pick(kwargs, _PIPELINE_FIELDS)
    payload.setdefault("steps", [])
    try:
        cfg = PipelineConfig.from_dict(payload)
    except Exception as exc:
        return tool_error("create_pipeline", str(exc), code="invalid_input")
    try:
        async with session_factory() as session:
            created = await factory(session).create(cfg)
            await session.commit()
        return tool_ok(
            "create_pipeline",
            pipeline={
                "name": created.name,
                "mode": created.mode,
                "max_steps": created.max_steps,
            },
        )
    except Exception as exc:
        logger.warning("create_pipeline failed: %s", exc)
        return tool_error("create_pipeline", str(exc), code="error")


async def _list_pipelines_execute(
    tool_deps: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """List pipeline definitions (name / mode / max_steps / tools_allowed)."""
    factory, session_factory = _wiring(tool_deps, "pipeline_service_factory")
    if factory is None or session_factory is None:
        return tool_error("list_pipelines", "tool_deps not injected", code="not_wired")
    try:
        async with session_factory() as session:
            summaries = await factory(session).list_summaries()
        return tool_ok("list_pipelines", items=summaries, count=len(summaries))
    except Exception as exc:
        logger.warning("list_pipelines failed: %s", exc)
        return tool_error("list_pipelines", str(exc), code="error")


async def _delete_pipeline_execute(
    tool_deps: Any = None, name: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Delete a pipeline definition by name."""
    factory, session_factory = _wiring(tool_deps, "pipeline_service_factory")
    if factory is None or session_factory is None:
        return tool_error("delete_pipeline", "tool_deps not injected", code="not_wired")
    if not name:
        return tool_error("delete_pipeline", "name is required", code="invalid_input")
    try:
        async with session_factory() as session:
            deleted = await factory(session).delete(name)
            await session.commit()
        if not deleted:
            return tool_error("delete_pipeline", "pipeline not found", code="not_found")
        return tool_ok("delete_pipeline", name=name)
    except Exception as exc:
        logger.warning("delete_pipeline failed: %s", exc)
        return tool_error("delete_pipeline", str(exc), code="error")


# ---------------------------------------------------------------------------
# Templates (aggregation / digest templates)
# ---------------------------------------------------------------------------


async def _create_template_execute(
    tool_deps: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Create (idempotent upsert) a custom digest template from LLM-supplied fields."""
    factory, session_factory = _wiring(tool_deps, "template_service_factory")
    if factory is None or session_factory is None:
        return tool_error("create_template", "tool_deps not injected", code="not_wired")
    try:
        cfg = TemplateConfig(**_pick(kwargs, _TEMPLATE_FIELDS))
    except Exception as exc:
        return tool_error("create_template", str(exc), code="invalid_input")
    try:
        async with session_factory() as session:
            created = await factory(session).create(cfg)
            payload = {
                "id": str(created.id),
                "name": created.name,
                "base_template": created.base_template,
                "status": created.status,
            }
            await session.commit()
        return tool_ok("create_template", template=payload)
    except TemplateValidationError as exc:
        return tool_error("create_template", str(exc), code="invalid_input")
    except Exception as exc:
        logger.warning("create_template failed: %s", exc)
        return tool_error("create_template", str(exc), code="error")


async def _list_templates_execute(
    tool_deps: Any = None, limit: int = 20, **kwargs: Any
) -> dict[str, Any]:
    """List custom templates (id / name / base_template / default_format / status)."""
    factory, session_factory = _wiring(tool_deps, "template_service_factory")
    if factory is None or session_factory is None:
        return tool_error("list_templates", "tool_deps not injected", code="not_wired")
    try:
        async with session_factory() as session:
            result = await factory(session).list_paginated(limit=min(int(limit), 100))
            items = [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "base_template": t.base_template,
                    "default_format": t.default_format,
                    "status": t.status,
                }
                for t in result["items"]
            ]
        return tool_ok("list_templates", items=items, count=len(items))
    except Exception as exc:
        logger.warning("list_templates failed: %s", exc)
        return tool_error("list_templates", str(exc), code="error")


async def _delete_template_execute(
    tool_deps: Any = None, name: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Delete a custom template by name."""
    factory, session_factory = _wiring(tool_deps, "template_service_factory")
    if factory is None or session_factory is None:
        return tool_error("delete_template", "tool_deps not injected", code="not_wired")
    if not name:
        return tool_error("delete_template", "name is required", code="invalid_input")
    try:
        async with session_factory() as session:
            service = factory(session)
            row = await service.get_by_name(name)
            if row is None:
                return tool_error(
                    "delete_template", "template not found", code="not_found"
                )
            await service.delete(row.id)
            await session.commit()
        return tool_ok("delete_template", name=name)
    except Exception as exc:
        logger.warning("delete_template failed: %s", exc)
        return tool_error("delete_template", str(exc), code="error")
