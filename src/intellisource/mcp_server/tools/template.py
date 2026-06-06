"""Custom digest template CRUD MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from intellisource.config.template_models import (
    TemplateConfig,
    TemplateValidationError,
)
from intellisource.mcp_server._serialize import only_set
from intellisource.mcp_server._types import SessionFactory
from intellisource.template.service import TemplateService


def register_template_tools(mcp: FastMCP, session_cm: SessionFactory) -> None:
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
        fields = only_set(
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
