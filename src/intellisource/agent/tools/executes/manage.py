"""Management (CRUD) tool execute functions: sources / subscriptions / pipelines.

Exposes the control-plane domain services to the agent so an LLM can provision
and inspect sources, subscriptions and pipeline definitions. The services are
injected via ``ToolDeps`` factories (constructed in the composition root); this
module imports only the cross-cutting config value objects, never a domain
service package, so the agent layer gains no static edge to those services.

``MANAGEMENT_TOOL_DEFS`` (defined at the end) co-locates each tool's JSON-schema
descriptor with the execute function it wraps; the registry installs the list
via ``register_management_tools``.
"""

from __future__ import annotations

from typing import Any

from intellisource.agent.tools._spec import ToolDefinition
from intellisource.agent.tools.executes._crud import (
    _crud,
    _parse_uuid,
    _ToolInputError,
    _validated,
)
from intellisource.agent.tools.results import tool_error, tool_ok
from intellisource.config.models import SourceConfig
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.template_models import TemplateConfig, TemplateValidationError

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

# Patch field sets route straight to ``Service.patch`` → ``repo.update`` (any
# column), so they may include ``status`` which the create-side config value
# objects (SourceConfig / SubscriptionConfig) do not accept.
_SOURCE_PATCH_FIELDS = (*_SOURCE_FIELDS, "status")
_SUB_PATCH_FIELDS = (*_SUB_FIELDS, "status")


def _pick(kwargs: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {k: kwargs[k] for k in fields if k in kwargs}


def _serialize_source(s: Any) -> dict[str, Any]:
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


def _serialize_subscription(s: Any) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "channel": s.channel,
        "status": s.status,
        "frequency": getattr(s, "frequency", None),
        "match_rules": dict(getattr(s, "match_rules", None) or {}),
    }


def _serialize_template(t: Any) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "name": t.name,
        "base_template": t.base_template,
        "formats": list(getattr(t, "formats", None) or []),
        "default_format": t.default_format,
        "status": t.status,
    }


def _serialize_pipeline(cfg: Any) -> dict[str, Any]:
    """Project a PipelineConfig to the full editable shape (get-before-update)."""
    return {
        "name": cfg.name,
        "mode": cfg.mode,
        "max_steps": cfg.max_steps,
        "on_failure": cfg.on_failure,
        "steps": cfg.steps,
        "tools_allowed": cfg.tools_allowed,
        "tools_denied": cfg.tools_denied,
        "system_prompt": cfg.system_prompt,
        "max_tokens_budget": cfg.max_tokens_budget,
        "agent_mode": cfg.agent_mode,
        "tool_permissions": cfg.tool_permissions,
    }


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


@_crud("create_source", "source_service_factory")
async def _create_source_execute(
    factory: Any, session_factory: Any, **kwargs: Any
) -> dict[str, Any]:
    """Create (idempotent upsert) a source from LLM-supplied fields."""
    cfg = _validated(lambda: SourceConfig(**_pick(kwargs, _SOURCE_FIELDS)))
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


@_crud("list_sources", "source_service_factory")
async def _list_sources_execute(
    factory: Any, session_factory: Any, limit: int = 20, **kwargs: Any
) -> dict[str, Any]:
    """List sources (id / name / type / url / status)."""
    limit = int(limit)
    async with session_factory() as session:
        result = await factory(session).list_paginated(limit=min(limit, 100))
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


@_crud("get_source", "source_service_factory")
async def _get_source_execute(
    factory: Any, session_factory: Any, source_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Fetch a single source by id."""
    sid = _parse_uuid(source_id, "source_id")
    async with session_factory() as session:
        row = await factory(session).get(sid)
    if row is None:
        return tool_error("get_source", "source not found", code="not_found")
    return tool_ok("get_source", source=_serialize_source(row))


@_crud("update_source", "source_service_factory")
async def _update_source_execute(
    factory: Any, session_factory: Any, source_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Partial-update an existing source by id (real patch, not create-upsert)."""
    sid = _parse_uuid(source_id, "source_id")
    fields = _pick(kwargs, _SOURCE_PATCH_FIELDS)
    if not fields:
        raise _ToolInputError("no fields to update")
    async with session_factory() as session:
        updated = await factory(session).patch(sid, fields)
        if updated is None:
            return tool_error("update_source", "source not found", code="not_found")
        payload = _serialize_source(updated)
        await session.commit()
    return tool_ok("update_source", source=payload)


@_crud("delete_source", "source_service_factory")
async def _delete_source_execute(
    factory: Any, session_factory: Any, source_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Soft-delete a source by id (status='paused')."""
    sid = _parse_uuid(source_id, "source_id")
    async with session_factory() as session:
        deleted = await factory(session).delete(sid)
        await session.commit()
    if not deleted:
        return tool_error("delete_source", "source not found", code="not_found")
    return tool_ok("delete_source", source_id=str(sid))


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


@_crud("create_subscription", "subscription_service_factory")
async def _create_subscription_execute(
    factory: Any, session_factory: Any, **kwargs: Any
) -> dict[str, Any]:
    """Create a subscription from LLM-supplied fields."""
    cfg = _validated(lambda: SubscriptionConfig(**_pick(kwargs, _SUB_FIELDS)))
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


@_crud("list_subscriptions", "subscription_service_factory")
async def _list_subscriptions_execute(
    factory: Any, session_factory: Any, limit: int = 20, **kwargs: Any
) -> dict[str, Any]:
    """List subscriptions (id / name / channel / status)."""
    limit = int(limit)
    async with session_factory() as session:
        result = await factory(session).list_paginated(limit=min(limit, 100))
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


@_crud("get_subscription", "subscription_service_factory")
async def _get_subscription_execute(
    factory: Any, session_factory: Any, subscription_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Fetch a single subscription by id."""
    sid = _parse_uuid(subscription_id, "subscription_id")
    async with session_factory() as session:
        row = await factory(session).get(sid)
    if row is None:
        return tool_error(
            "get_subscription", "subscription not found", code="not_found"
        )
    return tool_ok("get_subscription", subscription=_serialize_subscription(row))


@_crud("update_subscription", "subscription_service_factory")
async def _update_subscription_execute(
    factory: Any, session_factory: Any, subscription_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Partial-update an existing subscription by id (real patch)."""
    sid = _parse_uuid(subscription_id, "subscription_id")
    fields = _pick(kwargs, _SUB_PATCH_FIELDS)
    if not fields:
        raise _ToolInputError("no fields to update")
    async with session_factory() as session:
        updated = await factory(session).patch(sid, fields)
        if updated is None:
            return tool_error(
                "update_subscription", "subscription not found", code="not_found"
            )
        payload = _serialize_subscription(updated)
        await session.commit()
    return tool_ok("update_subscription", subscription=payload)


@_crud("delete_subscription", "subscription_service_factory")
async def _delete_subscription_execute(
    factory: Any, session_factory: Any, subscription_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Soft-delete a subscription by id (status='paused')."""
    sid = _parse_uuid(subscription_id, "subscription_id")
    async with session_factory() as session:
        deleted = await factory(session).delete(sid)
        await session.commit()
    if not deleted:
        return tool_error(
            "delete_subscription", "subscription not found", code="not_found"
        )
    return tool_ok("delete_subscription", subscription_id=str(sid))


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------


@_crud("get_pipeline", "pipeline_service_factory")
async def _get_pipeline_execute(
    factory: Any, session_factory: Any, name: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Fetch one pipeline definition's full config by name (get-before-update)."""
    if not name:
        raise _ToolInputError("name is required")
    async with session_factory() as session:
        cfg = await factory(session).get(name)
    if cfg is None:
        return tool_error("get_pipeline", "pipeline not found", code="not_found")
    return tool_ok("get_pipeline", pipeline=_serialize_pipeline(cfg))


@_crud("create_pipeline", "pipeline_service_factory")
async def _create_pipeline_execute(
    factory: Any, session_factory: Any, **kwargs: Any
) -> dict[str, Any]:
    """Create (idempotent upsert) a pipeline definition from LLM-supplied fields."""
    payload = _pick(kwargs, _PIPELINE_FIELDS)
    payload.setdefault("steps", [])
    cfg = _validated(lambda: PipelineConfig.from_dict(payload))
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


@_crud("list_pipelines", "pipeline_service_factory")
async def _list_pipelines_execute(
    factory: Any, session_factory: Any, **kwargs: Any
) -> dict[str, Any]:
    """List pipeline definitions (name / mode / max_steps / tools_allowed)."""
    async with session_factory() as session:
        summaries = await factory(session).list_summaries()
    return tool_ok("list_pipelines", items=summaries, count=len(summaries))


@_crud("update_pipeline", "pipeline_service_factory")
async def _update_pipeline_execute(
    factory: Any, session_factory: Any, name: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Partial-update an existing pipeline definition by name (real patch).

    Distinct from ``create_pipeline``: it overlays only the supplied fields onto
    the persisted definition and returns ``not_found`` when the name is absent,
    rather than minting a new definition from defaults.
    """
    if not name:
        raise _ToolInputError("name is required")
    # ``name`` is the immutable path identifier — never part of the patch body.
    fields = _pick(kwargs, tuple(f for f in _PIPELINE_FIELDS if f != "name"))
    if not fields:
        raise _ToolInputError("no fields to update")
    async with session_factory() as session:
        updated = await factory(session).update(name, fields)
        if updated is None:
            return tool_error("update_pipeline", "pipeline not found", code="not_found")
        payload = {
            "name": updated.name,
            "mode": updated.mode,
            "max_steps": updated.max_steps,
        }
        await session.commit()
    return tool_ok("update_pipeline", pipeline=payload)


@_crud("delete_pipeline", "pipeline_service_factory")
async def _delete_pipeline_execute(
    factory: Any, session_factory: Any, name: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Delete a pipeline definition by name."""
    if not name:
        raise _ToolInputError("name is required")
    async with session_factory() as session:
        deleted = await factory(session).delete(name)
        await session.commit()
    if not deleted:
        return tool_error("delete_pipeline", "pipeline not found", code="not_found")
    return tool_ok("delete_pipeline", name=name)


# ---------------------------------------------------------------------------
# Templates (aggregation / digest templates)
# ---------------------------------------------------------------------------


@_crud("create_template", "template_service_factory")
async def _create_template_execute(
    factory: Any, session_factory: Any, **kwargs: Any
) -> dict[str, Any]:
    """Create (idempotent upsert) a custom digest template from LLM-supplied fields."""
    cfg = _validated(lambda: TemplateConfig(**_pick(kwargs, _TEMPLATE_FIELDS)))
    async with session_factory() as session:
        try:
            created = await factory(session).create(cfg)
        except TemplateValidationError as exc:
            raise _ToolInputError(str(exc)) from exc
        payload = {
            "id": str(created.id),
            "name": created.name,
            "base_template": created.base_template,
            "status": created.status,
        }
        await session.commit()
    return tool_ok("create_template", template=payload)


@_crud("get_template", "template_service_factory")
async def _get_template_execute(
    factory: Any, session_factory: Any, name: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Fetch a single custom template by name."""
    if not name:
        raise _ToolInputError("name is required")
    async with session_factory() as session:
        row = await factory(session).get_by_name(name)
    if row is None:
        return tool_error("get_template", "template not found", code="not_found")
    return tool_ok("get_template", template=_serialize_template(row))


@_crud("update_template", "template_service_factory")
async def _update_template_execute(
    factory: Any, session_factory: Any, name: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Partial-update an existing custom template by name (real patch)."""
    if not name:
        raise _ToolInputError("name is required")
    # ``name`` is the immutable identifier — never part of the patch body.
    fields = _pick(kwargs, tuple(f for f in _TEMPLATE_FIELDS if f != "name"))
    if not fields:
        raise _ToolInputError("no fields to update")
    async with session_factory() as session:
        service = factory(session)
        row = await service.get_by_name(name)
        if row is None:
            return tool_error("update_template", "template not found", code="not_found")
        try:
            updated = await service.patch(row.id, fields)
        except TemplateValidationError as exc:
            raise _ToolInputError(str(exc)) from exc
        if updated is None:
            return tool_error("update_template", "template not found", code="not_found")
        payload = _serialize_template(updated)
        await session.commit()
    return tool_ok("update_template", template=payload)


@_crud("list_templates", "template_service_factory")
async def _list_templates_execute(
    factory: Any, session_factory: Any, limit: int = 20, **kwargs: Any
) -> dict[str, Any]:
    """List custom templates (id / name / base_template / default_format / status)."""
    limit = int(limit)
    async with session_factory() as session:
        result = await factory(session).list_paginated(limit=min(limit, 100))
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


@_crud("delete_template", "template_service_factory")
async def _delete_template_execute(
    factory: Any, session_factory: Any, name: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Delete a custom template by name."""
    if not name:
        raise _ToolInputError("name is required")
    async with session_factory() as session:
        service = factory(session)
        row = await service.get_by_name(name)
        if row is None:
            return tool_error("delete_template", "template not found", code="not_found")
        await service.delete(row.id)
        await session.commit()
    return tool_ok("delete_template", name=name)


# ---------------------------------------------------------------------------
# Tool descriptors (co-located with the execute functions above)
# ---------------------------------------------------------------------------


MANAGEMENT_TOOL_DEFS: list[ToolDefinition] = [
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
        name="get_pipeline",
        description=(
            "Fetch one pipeline definition's full config by name (mode, steps,"
            " max_steps, on_failure, tools_allowed/denied, system_prompt,"
            " agent_mode, max_tokens_budget, tool_permissions). Call before"
            " update_pipeline to edit from the current definition."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the pipeline to fetch.",
                }
            },
            "required": ["name"],
        },
        execute=_get_pipeline_execute,
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
