"""Source CRUD tool execute functions + descriptors."""

from __future__ import annotations

from typing import Any

from intellisource.agent.tools._spec import ToolDefinition
from intellisource.agent.tools.executes._crud import (
    _crud,
    _parse_uuid,
    _ToolInputError,
    _validated,
)
from intellisource.agent.tools.executes.manage._shared import _pick
from intellisource.agent.tools.results import tool_error, tool_ok
from intellisource.config.models import SourceConfig

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
# Patch field set routes straight to ``Service.patch`` → ``repo.update`` (any
# column), so it may include ``status`` which the create-side SourceConfig does
# not accept.
_SOURCE_PATCH_FIELDS = (*_SOURCE_FIELDS, "status")


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


SOURCE_TOOL_DEFS: list[ToolDefinition] = [
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
]
