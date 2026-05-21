"""AgentRunner dual-mode execution engine.

Supports strict mode (sequential tool execution) and flexible mode
(LLM agent loop). Both modes persist results to TaskChain (E-008).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from intellisource.agent.tools import ToolDefinition
from intellisource.core.errors import ErrorCategory, IntelliSourceError
from intellisource.storage.models import TaskChain
from intellisource.storage.repositories.task_chain import TaskChainRepository

if TYPE_CHECKING:
    from intellisource.pipeline.engine import PipelineEngine

logger = logging.getLogger(__name__)


class AgentRunner:
    """Dual-mode agent execution engine."""

    _MAX_RETRIES: int = 3

    def __init__(
        self,
        tool_registry: Any,
        llm_gateway: Any | None = None,
        *,
        pipeline_engine: PipelineEngine | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._llm_gateway = llm_gateway
        self._pipeline_engine = pipeline_engine

    # -- public API --------------------------------------------------

    async def execute(
        self,
        config: Any,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Dispatch to run_strict or run_flexible based on config.mode."""
        if config.mode == "strict":
            return await self.run_strict(config, params=params or {})
        return await self.run_flexible(
            config,
            user_message=kwargs.get("user_message", ""),
            session=kwargs.get("session", {}),
        )

    async def run_strict(
        self,
        config: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute pipeline steps sequentially without LLM."""
        results: list[dict[str, Any]] = []
        steps_executed = 0

        for step in config.steps:
            tool_name: str = step["tool"]
            step_params: dict[str, Any] = {**step.get("params", {})}
            tool_raw = self._tool_registry.get(tool_name)
            tool_fn = self._resolve_callable(tool_raw)

            try:
                result = await tool_fn(**step_params)
                results.append({"tool": tool_name, "output": result})
            except Exception:
                if config.on_failure == "abort":
                    steps_executed += 1
                    return await self._persist(
                        status="failed",
                        steps_executed=steps_executed,
                        results=results,
                        pipeline_name=config.name,
                        execution_mode="strict",
                    )
                if config.on_failure == "retry":
                    retry_result = await self._retry_step(
                        self._resolve_callable(tool_raw),
                        step_params,
                        tool_name,
                    )
                    results.append(retry_result)
                else:
                    # skip
                    results.append({"tool": tool_name, "output": None, "skipped": True})

            steps_executed += 1

        return await self._persist(
            status="success",
            steps_executed=steps_executed,
            results=results,
            pipeline_name=config.name,
            execution_mode="strict",
        )

    async def run_flexible(
        self,
        config: Any,
        user_message: str,
        session: dict[str, Any],
        *,
        max_tokens_budget: int | None = None,
    ) -> dict[str, Any]:
        """Run LLM agent loop with tool access.

        Args:
            config: Pipeline configuration.
            user_message: User input message.
            session: Session state dict.
            max_tokens_budget: Optional total token budget. When exceeded
                the loop stops and returns with budget_exhausted=True.
        """
        available_tools = self._filter_tools(config)
        tool_descriptors = [{"name": t} for t in available_tools]

        steps_executed = 0
        tokens_used = 0
        budget_exhausted = False
        messages: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []

        # Add system prompt if configured
        sys_prompt = getattr(config, "system_prompt", None)
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})

        messages.append({"role": "user", "content": user_message})

        if self._llm_gateway is None:
            msg = "LLM gateway is required for flexible mode"
            raise IntelliSourceError(msg, ErrorCategory.UNRECOVERABLE)
        while steps_executed < config.max_steps:
            response = await self._llm_gateway.chat(
                messages=messages,
                tools=tool_descriptors,
            )
            steps_executed += 1

            # Track token budget
            usage = response.metadata.get("usage", {})
            tokens_used += usage.get("total_tokens", 0)
            if max_tokens_budget is not None and tokens_used >= max_tokens_budget:
                budget_exhausted = True
                break

            tool_calls = response.metadata.get("tool_calls") or []
            finish_reason = response.metadata.get("finish_reason", "")
            done = finish_reason == "stop" or not tool_calls
            if done:
                break

            for tc in tool_calls:
                tc_name = tc.function.name if hasattr(tc, "function") else tc["name"]
                tc_id = tc.id if hasattr(tc, "id") else tc.get("id", "")
                if hasattr(tc, "function"):
                    import json as _json

                    raw_args = tc.function.arguments or "{}"
                    tc_args: dict[str, Any] = (
                        _json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    )
                else:
                    tc_args = tc.get("arguments", {})
                tool_raw = self._tool_registry.get(tc_name)
                if tool_raw is not None:
                    tool_fn = self._resolve_callable(tool_raw)
                    try:
                        result = await tool_fn(**tc_args)
                        import json as _json  # noqa: F811

                        messages.append(
                            {
                                "role": "tool",
                                "content": _json.dumps(result, default=str),
                                "tool_call_id": tc_id,
                            }
                        )
                        tool_results.append({"tool": tc_name, "output": result})
                    except Exception as exc:
                        logger.warning(
                            "Tool %s failed: %s",
                            tc_name,
                            exc,
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "content": f"Error: {exc}",
                                "tool_call_id": tc_id,
                            }
                        )
                        tool_results.append(
                            {
                                "tool": tc_name,
                                "output": None,
                                "error": str(exc),
                            }
                        )

        persist_result = await self._persist(
            status="success",
            steps_executed=steps_executed,
            results=tool_results,
            pipeline_name=config.name,
            execution_mode="flexible",
        )
        if budget_exhausted:
            persist_result["budget_exhausted"] = True
        return persist_result

    # -- private helpers ---------------------------------------------

    @staticmethod
    def _resolve_callable(tool: Any) -> Any:
        """Unwrap ToolDefinition to its execute callable if needed."""
        if isinstance(tool, ToolDefinition):
            return tool.execute
        return tool

    async def _retry_step(
        self,
        tool_fn: Any,
        params: dict[str, Any],
        tool_name: str,
    ) -> dict[str, Any]:
        """Retry a failed step up to _MAX_RETRIES times."""
        for _ in range(self._MAX_RETRIES):
            try:
                result = await tool_fn(**params)
                return {"tool": tool_name, "output": result}
            except Exception:
                continue
        return {"tool": tool_name, "output": None, "failed": True}

    def _filter_tools(self, config: Any) -> list[str]:
        """Build available tool list respecting allowed/denied."""
        all_tools: list[str] = self._tool_registry.list_tools()
        denied = set(config.tools_denied)
        allowed = set(config.tools_allowed)

        if allowed:
            tools = [t for t in all_tools if t in allowed]
        else:
            tools = list(all_tools)

        return [t for t in tools if t not in denied]

    async def _persist(
        self,
        *,
        status: str,
        steps_executed: int,
        results: list[dict[str, Any]],
        pipeline_name: str,
        task_chain_id: str | None = None,
        repo: TaskChainRepository | None = None,
        trigger_type: str = "manual",
        execution_mode: str = "strict",
    ) -> dict[str, Any]:
        """Persist result and return with task_chain_id.

        Args:
            task_chain_id: If provided by the caller (e.g. CeleryTasks),
                use it to correlate with the TaskChain DB record.
            repo: When provided and task_chain_id is absent, a new TaskChain
                record is written via repo.create().
            trigger_type: How the pipeline was triggered (e.g. 'manual', 'scheduled').
            execution_mode: Pipeline execution mode (e.g. 'strict', 'flexible').
        """
        if task_chain_id is not None:
            chain_id = task_chain_id
        elif repo is not None:
            task_chain = TaskChain(
                id=uuid.uuid4(),
                pipeline_name=pipeline_name,
                status=status,
                trigger_type=trigger_type,
                execution_mode=execution_mode,
                total_steps=steps_executed,
                completed_steps=steps_executed,
            )
            persisted = await repo.create(task_chain)
            chain_id = str(persisted.id)
        else:
            chain_id = str(uuid.uuid4())

        return {
            "status": status,
            "steps_executed": steps_executed,
            "results": results,
            "pipeline_name": pipeline_name,
            "task_chain_id": chain_id,
        }
