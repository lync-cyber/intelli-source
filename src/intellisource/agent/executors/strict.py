"""StrictExecutor — sequential tool execution without LLM."""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Coroutine

from intellisource.agent.deps import ToolDeps
from intellisource.agent.step_params import build_step_params, merge_step_output
from intellisource.agent.tools import ToolDefinition
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


class ToolDegradedError(Exception):
    """Raised in strict mode when a tool returns status='degraded'."""


class StrictExecutor:
    """Runs pipeline steps sequentially without LLM involvement."""

    _MAX_RETRIES: int = 3

    def __init__(
        self,
        tool_registry: Any,
        emit_pipeline_start: Callable[..., Coroutine[Any, Any, None]],
        emit_tool_call: Callable[..., Coroutine[Any, Any, None]],
        emit_pipeline_error: Callable[..., Coroutine[Any, Any, None]],
        persist: Callable[..., Coroutine[Any, Any, dict[str, Any]]],
    ) -> None:
        self._tool_registry = tool_registry
        self._emit_pipeline_start = emit_pipeline_start
        self._emit_tool_call = emit_tool_call
        self._emit_pipeline_error = emit_pipeline_error
        self._persist = persist

    async def run(
        self,
        config: Any,
        params: dict[str, Any],
        *,
        tool_deps: ToolDeps | None = None,
    ) -> dict[str, Any]:
        """Execute pipeline steps sequentially without LLM."""
        results: list[dict[str, Any]] = []
        steps_executed = 0
        step_context: dict[str, Any] = dict(params)
        chain_id = str(uuid.uuid4())

        await self._emit_pipeline_start(config.name, chain_id, "strict")

        try:
            for step in config.steps:
                tool_name: str = step["tool"]
                step_params = build_step_params(
                    step,
                    runtime_params=params,
                    step_context=step_context,
                    tool_deps=tool_deps,
                )
                tool_raw = self._tool_registry.get(tool_name)
                tool_fn = _resolve_callable(tool_raw)

                t0 = time.monotonic()
                try:
                    result = await tool_fn(**step_params)
                    if isinstance(result, dict) and result.get("status") == "degraded":
                        reason = result.get("reason", "")
                        await self._emit_tool_call(
                            config.name,
                            chain_id,
                            tool_name,
                            (time.monotonic() - t0) * 1000.0,
                            "error",
                            error=f"degraded: {reason}",
                        )
                        await self._emit_pipeline_error(
                            config.name,
                            chain_id,
                            f"tool {tool_name} degraded: {reason}",
                        )
                        raise ToolDegradedError(
                            f"tool {tool_name} returned degraded: {reason}"
                        )
                    await self._emit_tool_call(
                        config.name,
                        chain_id,
                        tool_name,
                        (time.monotonic() - t0) * 1000.0,
                        "success",
                    )
                    results.append({"tool": tool_name, "output": result})
                    merge_step_output(tool_name, result, step_context)
                except ToolDegradedError:
                    raise
                except Exception as exc:
                    await self._emit_tool_call(
                        config.name,
                        chain_id,
                        tool_name,
                        (time.monotonic() - t0) * 1000.0,
                        "error",
                        error=str(exc),
                    )
                    if config.on_failure == "abort":
                        steps_executed += 1
                        return await self._persist(
                            status="failed",
                            steps_executed=steps_executed,
                            results=results,
                            pipeline_name=config.name,
                            execution_mode="strict",
                            task_chain_id=chain_id,
                        )
                    if config.on_failure == "retry":
                        retry_result = await _retry_step(
                            _resolve_callable(tool_raw),
                            step_params,
                            tool_name,
                            self._MAX_RETRIES,
                        )
                        results.append(retry_result)
                    else:
                        results.append(
                            {"tool": tool_name, "output": None, "skipped": True}
                        )

                steps_executed += 1

            return await self._persist(
                status="success",
                steps_executed=steps_executed,
                results=results,
                pipeline_name=config.name,
                execution_mode="strict",
                task_chain_id=chain_id,
            )
        except Exception as exc:
            await self._emit_pipeline_error(config.name, chain_id, str(exc))
            raise


def _resolve_callable(tool: Any) -> Any:
    """Unwrap ToolDefinition to its execute callable if needed."""
    if isinstance(tool, ToolDefinition):
        return tool.execute
    return tool


async def _retry_step(
    tool_fn: Any,
    params: dict[str, Any],
    tool_name: str,
    max_retries: int,
) -> dict[str, Any]:
    """Retry a failed step up to max_retries times."""
    for attempt in range(max_retries):
        try:
            result = await tool_fn(**params)
            return {"tool": tool_name, "output": result}
        except Exception as exc:
            logger.debug(
                "strict step retry failed tool=%s attempt=%d/%d: %s",
                tool_name,
                attempt + 1,
                max_retries,
                exc,
            )
            continue
    return {"tool": tool_name, "output": None, "failed": True}
