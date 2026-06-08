"""Custom digest-template CRUD tool execute functions + descriptors."""

from __future__ import annotations

from typing import Any

from intellisource.agent.tools._spec import ToolDefinition
from intellisource.agent.tools.executes._crud import (
    _crud,
    _ToolInputError,
    _validated,
)
from intellisource.agent.tools.executes.manage._shared import _pick
from intellisource.agent.tools.results import tool_error, tool_ok
from intellisource.config.template_models import TemplateConfig, TemplateValidationError

_TEMPLATE_FIELDS = (
    "name",
    "base_template",
    "formats",
    "default_format",
    "jinja_source",
    "aggregate_config",
    "status",
)


def _serialize_template(t: Any) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "name": t.name,
        "base_template": t.base_template,
        "formats": list(getattr(t, "formats", None) or []),
        "default_format": t.default_format,
        "status": t.status,
    }


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


TEMPLATE_TOOL_DEFS: list[ToolDefinition] = [
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
