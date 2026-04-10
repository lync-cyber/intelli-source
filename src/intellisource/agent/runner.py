"""AgentRunner dual-mode execution engine.

Supports strict mode (sequential tool execution) and flexible mode
(LLM agent loop). Both modes persist results to TaskChain (E-008).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from intellisource.agent.tools import ToolDefinition
from intellisource.core.errors import ErrorCategory, IntelliSourceError

logger = logging.getLogger(__name__)


class AgentRunner:
    """Dual-mode agent execution engine."""

    _MAX_RETRIES: int = 3

    def __init__(
        self,
        tool_registry: Any,
        llm_gateway: Any | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._llm_gateway = llm_gateway

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
                    return self._persist(
                        status="failed",
                        steps_executed=steps_executed,
                        results=results,
                        pipeline_name=config.name,
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

        return self._persist(
            status="success",
            steps_executed=steps_executed,
            results=results,
            pipeline_name=config.name,
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
            usage = response.get("usage", {})
            tokens_used += usage.get("total_tokens", 0)
            if max_tokens_budget is not None and tokens_used >= max_tokens_budget:
                budget_exhausted = True
                break

            if response.get("done") or not response.get("tool_calls"):
                break

            for tc in response["tool_calls"]:
                tool_raw = self._tool_registry.get(tc["name"])
                if tool_raw is not None:
                    tool_fn = self._resolve_callable(tool_raw)
                    try:
                        result = await tool_fn(**tc.get("arguments", {}))
                        import json as _json

                        messages.append(
                            {
                                "role": "tool",
                                "content": _json.dumps(result, default=str),
                                "tool_call_id": tc.get("id", ""),
                            }
                        )
                    except Exception as exc:
                        logger.warning(
                            "Tool %s failed: %s",
                            tc["name"],
                            exc,
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "content": f"Error: {exc}",
                                "tool_call_id": tc.get("id", ""),
                            }
                        )

        persist_result = self._persist(
            status="success",
            steps_executed=steps_executed,
            results=[],
            pipeline_name=config.name,
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

    def _persist(
        self,
        *,
        status: str,
        steps_executed: int,
        results: list[dict[str, Any]],
        pipeline_name: str,
        task_chain_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist result and return with task_chain_id.

        Args:
            task_chain_id: If provided by the caller (e.g. CeleryTasks),
                use it to correlate with the TaskChain DB record.
                Otherwise a transient UUID is generated.
        """
        # [ASSUMPTION] Generates a local UUID when no upstream id is
        # provided. Replace with TaskChainRepository write when the
        # real persistence layer is integrated.
        return {
            "status": status,
            "steps_executed": steps_executed,
            "results": results,
            "pipeline_name": pipeline_name,
            "task_chain_id": task_chain_id or str(uuid.uuid4()),
        }
