"""Execution-control tool execute functions: trigger a pipeline run + poll status.

Lets an LLM dispatch a persisted pipeline and read back the resulting TaskChain
status. The Celery dispatcher and the TaskChain repository are injected via
``ToolDeps`` factories
(constructed in the composition root); this module imports no scheduler or
storage package directly, so the agent layer stays dependency-injected and the
tools are unit-testable without a broker or database.
"""

from __future__ import annotations

import uuid
from typing import Any

from intellisource.agent.deps import ToolDeps
from intellisource.agent.tools._spec import ToolDefinition
from intellisource.agent.tools.executes._deps import resolve_factories
from intellisource.agent.tools.results import tool_error, tool_ok
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


async def _run_pipeline_execute(
    tool_deps: ToolDeps | None = None,
    name: str = "",
    params: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Dispatch a persisted pipeline run via the injected task dispatcher."""
    if not name:
        return tool_error("run_pipeline", "name is required", code="invalid_input")
    dispatcher = getattr(tool_deps, "task_dispatcher", None)
    service_factory, session_factory = resolve_factories(
        tool_deps, "pipeline_service_factory"
    )
    if dispatcher is None or service_factory is None or session_factory is None:
        return tool_error("run_pipeline", "tool_deps not injected", code="not_wired")
    # Confirm the pipeline exists before hitting the broker so an unknown or
    # path-traversal name never dispatches a doomed task.
    try:
        async with session_factory() as session:
            existing = await service_factory(session).get(name)
    except Exception as exc:
        logger.warning("run_pipeline lookup failed: %s", exc)
        return tool_error("run_pipeline", str(exc), code="error")
    if existing is None:
        return tool_error(
            "run_pipeline", f"pipeline {name!r} not found", code="not_found"
        )
    # Pass a pre-generated TaskChain id to the worker so the id returned here is
    # the one get_task_status reads. Kept distinct from params["task_id"], which
    # the worker consumes as the idempotency lock key.
    chain_id = str(uuid.uuid4())
    run_params = {**(params or {}), "task_chain_id": chain_id}
    try:
        result = dispatcher(name, run_params)
    except Exception as exc:
        logger.warning("run_pipeline dispatch failed: %s", exc)
        return tool_error("run_pipeline", str(exc), code="dispatch_failed")
    celery_task_id = str(getattr(result, "id", result))
    return tool_ok(
        "run_pipeline",
        task_chain_id=chain_id,
        celery_task_id=celery_task_id,
        pipeline=name,
    )


async def _get_task_status_execute(
    tool_deps: ToolDeps | None = None,
    task_chain_id: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Return the status of a TaskChain by id (nested under ``task``)."""
    factory, session_factory = resolve_factories(tool_deps, "task_chain_repo_factory")
    if factory is None or session_factory is None:
        return tool_error("get_task_status", "tool_deps not injected", code="not_wired")
    if not task_chain_id:
        return tool_error(
            "get_task_status", "task_chain_id is required", code="invalid_input"
        )
    try:
        async with session_factory() as session:
            chain = await factory(session).get(str(task_chain_id))
    except Exception as exc:
        logger.warning("get_task_status failed: %s", exc)
        return tool_error("get_task_status", str(exc), code="error")
    if chain is None:
        return tool_error("get_task_status", "task chain not found", code="not_found")
    # Nest under "task" so the run state does not collide with the tool-envelope
    # "status" (ok/error) key.
    return tool_ok(
        "get_task_status",
        task={
            "task_chain_id": str(chain.id),
            "status": chain.status,
            "completed_steps": chain.completed_steps,
            "total_steps": chain.total_steps,
            "error_message": chain.error_message,
        },
    )


# ---------------------------------------------------------------------------
# Tool descriptors (co-located with the execute functions above)
# ---------------------------------------------------------------------------


RUN_TOOL_DEFS: list[ToolDefinition] = [
    ToolDefinition(
        name="run_pipeline",
        description=(
            "Trigger a run of a persisted pipeline by name via the task queue."
            " Returns {task_chain_id, celery_task_id}; poll task_chain_id with"
            " get_task_status to read run progress and result."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the persisted pipeline to run.",
                },
                "params": {
                    "type": "object",
                    "description": "Optional runtime params passed to the run.",
                },
            },
            "required": ["name"],
        },
        execute=_run_pipeline_execute,
        mutates_external_state=True,
    ),
    ToolDefinition(
        name="get_task_status",
        description=(
            "Get the status of a pipeline run by its task_chain_id"
            " (the task_chain_id returned by run_pipeline). Returns the run"
            " state (status / completed_steps / total_steps / error_message)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task_chain_id": {
                    "type": "string",
                    "description": "TaskChain UUID to poll.",
                }
            },
            "required": ["task_chain_id"],
        },
        execute=_get_task_status_execute,
    ),
]
