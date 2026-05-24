"""AgentRunner dual-mode execution engine.

Supports strict mode (sequential tool execution) and flexible mode
(LLM agent loop). Both modes persist results to TaskChain (E-008).
"""

from __future__ import annotations

import enum
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from intellisource.agent.step_params import build_step_params, merge_step_output
from intellisource.agent.tools import PermissionLevel, ToolDefinition
from intellisource.core.errors import ErrorCategory, IntelliSourceError
from intellisource.storage.models import TaskChain
from intellisource.storage.repositories.task_chain import TaskChainRepository

if TYPE_CHECKING:
    from intellisource.agent.deps import ToolDeps
    from intellisource.pipeline.engine import PipelineEngine

logger = logging.getLogger(__name__)

_ANALYZE_DENIED_TOOLS: frozenset[str] = frozenset({"distribute", "process"})


class AgentMode(str, enum.Enum):
    """Orthogonal execution mode for the flexible agent loop."""

    process = "process"
    analyze = "analyze"
    preview = "preview"


class AgentRunner:
    """Dual-mode agent execution engine."""

    _MAX_RETRIES: int = 3

    def __init__(
        self,
        tool_registry: Any,
        llm_gateway: Any | None = None,
        *,
        pipeline_engine: PipelineEngine | None = None,
        tool_deps: ToolDeps | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._llm_gateway = llm_gateway
        self._pipeline_engine = pipeline_engine
        self._tool_deps = tool_deps

    # -- public API --------------------------------------------------

    async def execute(
        self,
        config: Any,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Dispatch to run_strict, run_batch, or run_flexible based on config.mode."""
        tool_deps = kwargs.pop("tool_deps", self._tool_deps)
        runtime_params = params or {}
        if config.mode == "strict":
            return await self.run_strict(
                config, params=runtime_params, tool_deps=tool_deps
            )
        if config.mode == "batch":
            return await self.run_batch(
                config, params=runtime_params, tool_deps=tool_deps
            )
        return await self.run_flexible(
            config,
            user_message=kwargs.get("user_message", ""),
            session=kwargs.get("session", {}),
            tool_deps=tool_deps,
        )

    async def run_strict(
        self,
        config: Any,
        params: dict[str, Any],
        *,
        tool_deps: Any = None,
    ) -> dict[str, Any]:
        """Execute pipeline steps sequentially without LLM."""
        effective_deps = tool_deps if tool_deps is not None else self._tool_deps
        results: list[dict[str, Any]] = []
        steps_executed = 0
        step_context: dict[str, Any] = dict(params)

        for step in config.steps:
            tool_name: str = step["tool"]
            step_params = build_step_params(
                step,
                runtime_params=params,
                step_context=step_context,
                tool_deps=effective_deps,
            )
            tool_raw = self._tool_registry.get(tool_name)
            tool_fn = self._resolve_callable(tool_raw)

            try:
                result = await tool_fn(**step_params)
                results.append({"tool": tool_name, "output": result})
                merge_step_output(tool_name, result, step_context)
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

    async def run_batch(
        self,
        config: Any,
        params: dict[str, Any],
        *,
        tool_deps: Any = None,
    ) -> dict[str, Any]:
        """Execute processor pipeline for a single raw content_id (batch mode)."""
        effective_deps = tool_deps if tool_deps is not None else self._tool_deps
        content_id = str(params.get("content_id") or "")
        if not content_id:
            return await self._persist(
                status="failed",
                steps_executed=0,
                results=[],
                pipeline_name=config.name,
                execution_mode="batch",
            )

        from intellisource.agent.tools import _process_execute  # noqa: PLC0415

        output = await _process_execute(
            tool_deps=effective_deps,
            **params,
        )
        tool_results = [{"tool": "process", "output": output}]
        status = "success" if output.get("status") == "ok" else "failed"
        persist_result = await self._persist(
            status=status,
            steps_executed=max(len(config.steps), 1),
            results=tool_results,
            pipeline_name=config.name,
            execution_mode="batch",
        )
        inner_result = output.get("result")
        inner: dict[str, Any] = inner_result if isinstance(inner_result, dict) else {}
        raw_id = inner.get("raw_content_id") or content_id
        persist_result["content_id"] = raw_id
        processed_id = inner.get("content_id")
        if processed_id:
            persist_result["processed_content_id"] = processed_id
        return persist_result

    async def run_flexible(
        self,
        config: Any,
        user_message: str,
        session: dict[str, Any],
        *,
        max_tokens_budget: int | None = None,
        tool_deps: Any = None,
    ) -> dict[str, Any]:
        """Run LLM agent loop with tool access.

        Args:
            config: Pipeline configuration.
            user_message: User input message.
            session: Session state dict.
            max_tokens_budget: Optional total token budget. When exceeded
                the loop stops and returns with budget_exhausted=True.
            tool_deps: Optional dependency container injected into each tool call.
                Falls back to self._tool_deps when not provided.
        """
        agent_mode_str = getattr(config, "agent_mode", AgentMode.process.value)
        try:
            agent_mode = AgentMode(agent_mode_str)
        except ValueError:
            agent_mode = AgentMode.process

        effective_deps = tool_deps if tool_deps is not None else self._tool_deps
        available_tools = self._filter_tools(config, agent_mode=agent_mode)
        tool_descriptors = self._build_tool_descriptors(available_tools)
        effective_budget = (
            max_tokens_budget
            if max_tokens_budget is not None
            else getattr(config, "max_tokens_budget", None)
        )

        steps_executed = 0
        tokens_used = 0
        budget_exhausted = False
        final_answer = ""
        messages: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        preview_plan: list[dict[str, Any]] = []

        # Add system prompt if configured
        sys_prompt = getattr(config, "system_prompt", None)
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})

        messages.extend(self._session_messages(session))
        messages.append({"role": "user", "content": user_message})

        if effective_budget is not None and effective_budget <= 0:
            budget_exhausted = True

        if self._llm_gateway is None:
            msg = "LLM gateway is required for flexible mode"
            raise IntelliSourceError(msg, ErrorCategory.UNRECOVERABLE)

        while steps_executed < config.max_steps and not budget_exhausted:
            response = await self._llm_gateway.chat(
                messages=messages,
                tools=tool_descriptors,
            )
            steps_executed += 1

            # Track token budget
            usage = response.metadata.get("usage", {})
            tokens_used += usage.get("total_tokens", 0)
            budget_hit = (
                effective_budget is not None and tokens_used >= effective_budget
            )

            tool_calls = response.metadata.get("tool_calls") or []
            finish_reason = response.metadata.get("finish_reason", "")
            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            self._serialize_tool_call(tc) for tc in tool_calls
                        ],
                    }
                )
            elif response.content:
                final_answer = response.content

            if budget_hit:
                budget_exhausted = True
                break

            done = finish_reason == "stop" or not tool_calls
            if done:
                break

            pipeline_perms: dict[str, str] = (
                getattr(config, "tool_permissions", {}) or {}
            )

            for tc in tool_calls:
                tc_name, tc_id, tc_args = self._parse_tool_call(tc)

                # Runtime deny check (handles LLM hallucination of deny tools)
                _override = pipeline_perms.get(tc_name)
                if _override is not None:
                    _effective_perm = PermissionLevel(_override)
                else:
                    _tool_raw_perm = self._tool_registry.get(tc_name)
                    _effective_perm = (
                        _tool_raw_perm.permission_level
                        if isinstance(_tool_raw_perm, ToolDefinition)
                        else PermissionLevel.auto
                    )
                if _effective_perm is PermissionLevel.deny:
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                {"status": "denied_by_permission", "tool": tc_name}
                            ),
                            "tool_call_id": tc_id,
                        }
                    )
                    tool_results.append(
                        {
                            "tool": tc_name,
                            "status": "denied_by_permission",
                            "output": None,
                        }
                    )
                    continue

                if agent_mode is AgentMode.analyze and tc_name in _ANALYZE_DENIED_TOOLS:
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                {"status": "denied_by_analyze_mode", "tool": tc_name}
                            ),
                            "tool_call_id": tc_id,
                        }
                    )
                    tool_results.append(
                        {
                            "tool": tc_name,
                            "output": None,
                            "denied": True,
                            "reason": "analyze_mode",
                        }
                    )
                    continue

                if agent_mode is AgentMode.preview:
                    # Record without executing
                    preview_plan.append(
                        {
                            "tool": tc_name,
                            "args": tc_args,
                            "would_execute_at": datetime.now(
                                tz=timezone.utc
                            ).isoformat(),
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps({"status": "preview_skipped"}),
                            "tool_call_id": tc_id,
                        }
                    )
                    continue

                # Record pending_confirmation for confirm-level tools
                if _effective_perm is PermissionLevel.confirm:
                    logger.info(
                        "pending_confirmation",
                        extra={
                            "tool": tc_name,
                            "args": tc_args,
                            "tool_call_id": tc_id,
                        },
                    )
                    tool_results.append(
                        {
                            "tool": tc_name,
                            "status": "pending_confirmation",
                            "args": tc_args,
                            "tool_call_id": tc_id,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                {"status": "pending_confirmation", "tool": tc_name}
                            ),
                            "tool_call_id": tc_id,
                        }
                    )
                    continue

                if effective_deps is not None:
                    tc_args = {**tc_args, "tool_deps": effective_deps}
                tool_raw = self._tool_registry.get(tc_name)
                if tool_raw is not None:
                    tool_fn = self._resolve_callable(tool_raw)
                    try:
                        result = await tool_fn(**tc_args)

                        messages.append(
                            {
                                "role": "tool",
                                "content": json.dumps(result, default=str),
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

        if agent_mode is AgentMode.preview:
            persist_result = await self._persist(
                status="preview",
                steps_executed=steps_executed,
                results=tool_results,
                pipeline_name=config.name,
                execution_mode="flexible",
            )
            persist_result["plan"] = preview_plan
            persist_result["tokens_used"] = tokens_used
            return persist_result

        persist_result = await self._persist(
            status="success",
            steps_executed=steps_executed,
            results=tool_results,
            pipeline_name=config.name,
            execution_mode="flexible",
        )
        if budget_exhausted:
            persist_result["budget_exhausted"] = True
        persist_result["tokens_used"] = tokens_used
        if final_answer:
            persist_result["final_answer"] = final_answer
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

    def _filter_tools(
        self,
        config: Any,
        agent_mode: AgentMode = AgentMode.process,
    ) -> list[str]:
        """Build available tool list respecting config filters and permission levels."""
        all_tools: list[str] = self._tool_registry.list_tools()
        denied = set(config.tools_denied)
        allowed = set(config.tools_allowed)

        if agent_mode is AgentMode.analyze:
            denied = denied | _ANALYZE_DENIED_TOOLS

        if allowed:
            tools = [t for t in all_tools if t in allowed]
        else:
            tools = list(all_tools)

        # Resolve effective permission per tool (pipeline override > tool default)
        pipeline_perms: dict[str, str] = getattr(config, "tool_permissions", {}) or {}
        permission_denied: set[str] = set()
        for t in tools:
            override = pipeline_perms.get(t)
            if override is not None:
                effective = PermissionLevel(override)
            else:
                tool_def = self._tool_registry.get(t)
                effective = (
                    tool_def.permission_level
                    if isinstance(tool_def, ToolDefinition)
                    else PermissionLevel.auto
                )
            if effective is PermissionLevel.deny:
                permission_denied.add(t)

        return [t for t in tools if t not in denied and t not in permission_denied]

    def _build_tool_descriptors(self, tool_names: list[str]) -> list[dict[str, Any]]:
        """Build OpenAI-style function tool descriptors for LLMGateway.chat()."""
        descriptors: list[dict[str, Any]] = []
        for name in tool_names:
            tool = self._tool_registry.get(name)
            if isinstance(tool, ToolDefinition):
                description = tool.description
                parameters = tool.parameters
            else:
                description = ""
                parameters = {"type": "object", "properties": {}}
            descriptors.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
        return descriptors

    @staticmethod
    def _serialize_tool_call(tool_call: Any) -> dict[str, Any]:
        """Return an assistant-message tool_call payload for LLM continuity."""
        name, call_id, args = AgentRunner._parse_tool_call(tool_call)
        return {
            "id": call_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args, default=str),
            },
        }

    @staticmethod
    def _parse_tool_call(tool_call: Any) -> tuple[str, str, dict[str, Any]]:
        """Extract (name, id, arguments) from SDK-style or dict tool calls."""
        if hasattr(tool_call, "function"):
            name = str(tool_call.function.name)
            call_id = str(getattr(tool_call, "id", ""))
            raw_args = tool_call.function.arguments or "{}"
        elif isinstance(tool_call, dict) and isinstance(
            tool_call.get("function"), dict
        ):
            function = tool_call["function"]
            name = str(function["name"])
            call_id = str(tool_call.get("id", ""))
            raw_args = function.get("arguments", {})
        else:
            name = str(tool_call["name"])
            call_id = str(tool_call.get("id", ""))
            raw_args = tool_call.get("arguments", {})

        if isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError:
                parsed = {}
        else:
            parsed = raw_args
        return name, call_id, parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _session_messages(session: dict[str, Any]) -> list[dict[str, Any]]:
        """Return valid prior conversation messages from a session payload."""
        raw_messages = session.get("messages")
        if not isinstance(raw_messages, list):
            return []
        messages: list[dict[str, Any]] = []
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant", "tool"} and isinstance(content, str):
                messages.append({"role": role, "content": content})
        return messages

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
