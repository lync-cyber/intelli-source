"""Pipeline-definition CRUD tool execute functions + descriptors."""

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
from intellisource.config.pipeline_models import PipelineConfig

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


PIPELINE_TOOL_DEFS: list[ToolDefinition] = [
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
]
