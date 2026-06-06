"""Data source CRUD MCP tools."""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from intellisource.config.models import SourceConfig
from intellisource.mcp_server._serialize import only_set, source_dict
from intellisource.mcp_server._types import SessionFactory
from intellisource.source.service import SourceConfigService


def register_source_tools(mcp: FastMCP, session_cm: SessionFactory) -> None:
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
            return [source_dict(s) for s in result["items"]]

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
        return source_dict(row)

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
        fields = only_set(
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
            payload = source_dict(updated)
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
