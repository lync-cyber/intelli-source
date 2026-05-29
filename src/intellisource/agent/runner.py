"""AgentRunner dual-mode execution engine.

Supports strict mode (sequential tool execution) and flexible mode
(LLM agent loop). Both modes persist results to TaskChain (E-008).
"""

from __future__ import annotations

import enum
import time
import uuid
from typing import TYPE_CHECKING, Any, AsyncGenerator

from intellisource.agent.events import PipelineEventLogger
from intellisource.agent.executors.flexible import (
    _ANALYZE_DENIED_TOOLS,
    FlexibleLoop,
    _parse_tool_call,
    _resolve_callable,
    _serialize_tool_call,
    _session_messages,
)
from intellisource.agent.executors.strict import (
    StrictExecutor,
    ToolDegradedError,
    _retry_step,
)
from intellisource.agent.tools import PermissionLevel, ToolDefinition
from intellisource.observability.logging import get_logger
from intellisource.storage.models import TaskChain
from intellisource.storage.repositories.task_chain import TaskChainRepository

if TYPE_CHECKING:
    from intellisource.agent.deps import ToolDeps
    from intellisource.pipeline.engine import PipelineEngine

logger = get_logger(__name__)

__all__ = [
    "AgentMode",
    "AgentRunner",
    "ToolDegradedError",
    "_ANALYZE_DENIED_TOOLS",
]


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
        event_logger: PipelineEventLogger | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._llm_gateway = llm_gateway
        self._pipeline_engine = pipeline_engine
        self._tool_deps = tool_deps
        self._event_logger = event_logger

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
        executor = StrictExecutor(
            tool_registry=self._tool_registry,
            emit_pipeline_start=self._emit_pipeline_start,
            emit_tool_call=self._emit_tool_call,
            emit_pipeline_error=self._emit_pipeline_error,
            persist=self._persist,
        )
        return await executor.run(config, params, tool_deps=effective_deps)

    async def run_batch(
        self,
        config: Any,
        params: dict[str, Any],
        *,
        tool_deps: Any = None,
    ) -> dict[str, Any]:
        """Execute processor pipeline for a single raw content_id (batch mode)."""
        effective_deps = tool_deps if tool_deps is not None else self._tool_deps
        chain_id = str(uuid.uuid4())
        await self._emit_pipeline_start(config.name, chain_id, "batch")
        content_id = str(params.get("content_id") or "")
        if not content_id:
            return await self._persist(
                status="failed",
                steps_executed=0,
                results=[],
                pipeline_name=config.name,
                execution_mode="batch",
                task_chain_id=chain_id,
            )

        from intellisource.agent.tools import _process_execute  # noqa: PLC0415

        t0 = time.monotonic()
        try:
            output = await _process_execute(
                tool_deps=effective_deps,
                **params,
            )
            await self._emit_tool_call(
                config.name,
                chain_id,
                "process",
                (time.monotonic() - t0) * 1000.0,
                "success",
            )
        except Exception as exc:
            await self._emit_tool_call(
                config.name,
                chain_id,
                "process",
                (time.monotonic() - t0) * 1000.0,
                "error",
                error=str(exc),
            )
            await self._emit_pipeline_error(config.name, chain_id, str(exc))
            raise
        tool_results = [{"tool": "process", "output": output}]
        status = "success" if output.get("status") == "ok" else "failed"
        persist_result = await self._persist(
            status=status,
            steps_executed=max(len(config.steps), 1),
            results=tool_results,
            pipeline_name=config.name,
            execution_mode="batch",
            task_chain_id=chain_id,
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
        loop = FlexibleLoop(
            tool_registry=self._tool_registry,
            llm_gateway=self._llm_gateway,
            emit_pipeline_start=self._emit_pipeline_start,
            emit_tool_call=self._emit_tool_call,
            emit_llm_call=self._emit_llm_call,
            emit_pipeline_error=self._emit_pipeline_error,
            persist=self._persist,
        )
        return await loop.run(
            config,
            user_message,
            session,
            agent_mode=agent_mode,
            max_tokens_budget=max_tokens_budget,
            tool_deps=effective_deps,
        )

    async def run_flexible_stream(
        self,
        config: Any,
        user_message: str,
        session: dict[str, Any],
        *,
        max_tokens_budget: int | None = None,
        tool_deps: Any = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Streaming counterpart to ``run_flexible``.

        Drives the same FlexibleLoop tool loop as ``run_flexible`` but yields
        event dicts (step / sources / token / done / error) suitable for
        SSE relay. See ``FlexibleLoop.run_stream`` for the event contract.
        """
        agent_mode_str = getattr(config, "agent_mode", AgentMode.process.value)
        try:
            agent_mode = AgentMode(agent_mode_str)
        except ValueError:
            agent_mode = AgentMode.process

        effective_deps = tool_deps if tool_deps is not None else self._tool_deps
        loop = FlexibleLoop(
            tool_registry=self._tool_registry,
            llm_gateway=self._llm_gateway,
            emit_pipeline_start=self._emit_pipeline_start,
            emit_tool_call=self._emit_tool_call,
            emit_llm_call=self._emit_llm_call,
            emit_pipeline_error=self._emit_pipeline_error,
            persist=self._persist,
        )
        async for event in loop.run_stream(
            config,
            user_message,
            session,
            agent_mode=agent_mode,
            max_tokens_budget=max_tokens_budget,
            tool_deps=effective_deps,
        ):
            yield event

    # -- event helpers -----------------------------------------------

    async def _emit_pipeline_start(
        self, pipeline_name: str, chain_id: str, mode: str
    ) -> None:
        if self._event_logger is None:
            return
        await self._event_logger.pipeline_start(
            pipeline_name=pipeline_name,
            task_chain_id=chain_id,
            mode=mode,
        )

    async def _emit_tool_call(
        self,
        pipeline_name: str,
        chain_id: str,
        tool_name: str,
        duration_ms: float,
        status: str,
        error: str | None = None,
    ) -> None:
        if self._event_logger is None:
            return
        await self._event_logger.tool_call(
            pipeline_name=pipeline_name,
            task_chain_id=chain_id,
            tool_name=tool_name,
            duration_ms=duration_ms,
            status="error" if status == "error" else "success",
            error=error,
        )

    async def _emit_llm_call(
        self,
        pipeline_name: str,
        chain_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> None:
        if self._event_logger is None:
            return
        await self._event_logger.llm_call(
            pipeline_name=pipeline_name,
            task_chain_id=chain_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

    async def _emit_pipeline_complete(
        self,
        pipeline_name: str,
        chain_id: str,
        status: str,
        steps_executed: int,
    ) -> None:
        if self._event_logger is None:
            return
        await self._event_logger.pipeline_complete(
            pipeline_name=pipeline_name,
            task_chain_id=chain_id,
            status=status,
            steps_executed=steps_executed,
        )

    async def _emit_pipeline_error(
        self, pipeline_name: str, chain_id: str, error: str
    ) -> None:
        if self._event_logger is None:
            return
        await self._event_logger.pipeline_error(
            pipeline_name=pipeline_name,
            task_chain_id=chain_id,
            error=error,
        )

    # -- private helpers ---------------------------------------------

    @staticmethod
    def _resolve_callable(tool: Any) -> Any:
        """Unwrap ToolDefinition to its execute callable if needed."""
        return _resolve_callable(tool)

    async def _retry_step(
        self,
        tool_fn: Any,
        params: dict[str, Any],
        tool_name: str,
    ) -> dict[str, Any]:
        """Retry a failed step up to _MAX_RETRIES times."""
        return await _retry_step(tool_fn, params, tool_name, self._MAX_RETRIES)

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
            denied = denied | self._analyze_denied_tools(all_tools)

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

    def _analyze_denied_tools(self, candidate_names: list[str]) -> set[str]:
        """Resolve which tools are denied under analyze mode."""
        return {n for n in candidate_names if self._is_analyze_denied(n)}

    def _is_analyze_denied(self, name: str) -> bool:
        """Return True when ``name`` is denied under analyze mode."""
        tool_def = self._tool_registry.get(name)
        if isinstance(tool_def, ToolDefinition) and tool_def.mutates_external_state:
            return True
        return name in _ANALYZE_DENIED_TOOLS

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
        return _serialize_tool_call(tool_call)

    @staticmethod
    def _parse_tool_call(tool_call: Any) -> tuple[str, str, dict[str, Any]]:
        """Extract (name, id, arguments) from SDK-style or dict tool calls."""
        return _parse_tool_call(tool_call)

    @staticmethod
    def _session_messages(session: dict[str, Any]) -> list[dict[str, Any]]:
        """Return valid prior conversation messages from a session payload."""
        return _session_messages(session)

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
            raise ValueError(
                "_persist requires either task_chain_id or repo; both were None. "
                "Internal run_strict/run_batch/run_flexible always pre-generate "
                "chain_id, so this indicates an unexpected external caller."
            )

        await self._emit_pipeline_complete(
            pipeline_name, chain_id, status, steps_executed
        )

        return {
            "status": status,
            "steps_executed": steps_executed,
            "results": results,
            "pipeline_name": pipeline_name,
            "task_chain_id": chain_id,
        }
