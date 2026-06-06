"""Pipeline definition + run/status MCP tools."""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from intellisource.config.pipeline_models import PipelineConfig
from intellisource.mcp_server._serialize import only_set, pipeline_dict
from intellisource.mcp_server._types import SessionFactory
from intellisource.pipeline.definition_service import PipelineDefinitionService
from intellisource.storage.repositories.task_chain import TaskChainRepository


def register_pipeline_tools(mcp: FastMCP, session_cm: SessionFactory) -> None:
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
        return pipeline_dict(cfg)

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
        return pipeline_dict(created)

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
        fields = only_set(
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
                payload = pipeline_dict(updated)
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

    @mcp.tool(
        name="trigger_pipeline",
        description=(
            "Dispatch a run of a persisted pipeline via the task queue. Params:"
            " name, params (optional run kwargs). Returns {task_chain_id,"
            " celery_task_id}, or {error} when the name is unknown or the broker"
            " is unreachable. Poll task_chain_id with get_task_status."
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

        # Pass a pre-generated TaskChain id to the worker so the id returned
        # here is the one get_task_status reads.
        chain_id = str(_uuid.uuid4())
        run_params = {**(params or {}), "task_chain_id": chain_id}
        try:
            result = send_task_with_trace(
                "run_pipeline",
                kwargs={"pipeline_name": name, "params": run_params},
                celery_instance=celery_app,
            )
        except Exception as exc:
            return {"error": "dispatch_failed", "reason": str(exc)}
        return {
            "task_chain_id": chain_id,
            "celery_task_id": str(getattr(result, "id", result)),
        }

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
