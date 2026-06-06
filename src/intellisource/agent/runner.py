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
from intellisource.agent.executors.flexible import FlexibleLoop
from intellisource.agent.executors.persistence import TaskChainPersister
from intellisource.agent.executors.strict import (
    StrictExecutor,
    ToolDegradedError,
    _retry_step,
)
from intellisource.core.errors import CompositionNotInitialisedError
from intellisource.observability.logging import get_logger

if TYPE_CHECKING:
    from intellisource.agent.deps import ToolDeps
    from intellisource.pipeline.engine import PipelineEngine

logger = get_logger(__name__)

__all__ = [
    "AgentMode",
    "AgentRunner",
    "AgentRunnerHolder",
    "ToolDegradedError",
    "get_agent_runner_holder",
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
        self._persister = TaskChainPersister(event_logger)

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
        tool_deps: ToolDeps | None = None,
    ) -> dict[str, Any]:
        """Execute pipeline steps sequentially without LLM."""
        effective_deps = tool_deps if tool_deps is not None else self._tool_deps
        executor = StrictExecutor(
            tool_registry=self._tool_registry,
            emit_pipeline_start=self._emit_pipeline_start,
            emit_tool_call=self._emit_tool_call,
            emit_pipeline_error=self._emit_pipeline_error,
            persist=self._persister.persist,
        )
        return await executor.run(config, params, tool_deps=effective_deps)

    async def run_batch(
        self,
        config: Any,
        params: dict[str, Any],
        *,
        tool_deps: ToolDeps | None = None,
    ) -> dict[str, Any]:
        """Execute processor pipeline for a single raw content_id (batch mode)."""
        effective_deps = tool_deps if tool_deps is not None else self._tool_deps
        chain_id = str(uuid.uuid4())
        await self._emit_pipeline_start(config.name, chain_id, "batch")
        content_id = str(params.get("content_id") or "")
        if not content_id:
            return await self._persister.persist(
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
        persist_result = await self._persister.persist(
            status=status,
            steps_executed=max(len(config.steps), 1),
            results=tool_results,
            pipeline_name=config.name,
            execution_mode="batch",
            task_chain_id=chain_id,
        )
        results_list = output.get("results") or []
        first: dict[str, Any] = results_list[0] if results_list else {}
        raw_id = first.get("raw_content_id") or content_id
        persist_result["content_id"] = raw_id
        processed_id = first.get("content_id")
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
        tool_deps: ToolDeps | None = None,
        approved_calls: list[dict[str, Any]] | None = None,
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
            approved_calls: Human-in-the-loop confirmed tool calls (tool + args)
                executed before the loop, letting a confirm-gated action run.
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
            persist=self._persister.persist,
        )
        return await loop.run(
            config,
            user_message,
            session,
            agent_mode=agent_mode,
            max_tokens_budget=max_tokens_budget,
            tool_deps=effective_deps,
            approved_calls=approved_calls,
        )

    async def run_flexible_stream(
        self,
        config: Any,
        user_message: str,
        session: dict[str, Any],
        *,
        max_tokens_budget: int | None = None,
        tool_deps: ToolDeps | None = None,
        approved_calls: list[dict[str, Any]] | None = None,
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
            persist=self._persister.persist,
        )
        async for event in loop.run_stream(
            config,
            user_message,
            session,
            agent_mode=agent_mode,
            max_tokens_budget=max_tokens_budget,
            tool_deps=effective_deps,
            approved_calls=approved_calls,
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

    async def _retry_step(
        self,
        tool_fn: Any,
        params: dict[str, Any],
        tool_name: str,
    ) -> dict[str, Any]:
        """Retry a failed step up to _MAX_RETRIES times."""
        return await _retry_step(tool_fn, params, tool_name, self._MAX_RETRIES)


class AgentRunnerHolder:
    """Mutable single-slot container for the process-wide AgentRunner.

    Owned by the composition root: `install()` puts the assembled runner in
    (composition → agent, a forward edge); `get()` reads it (raising
    CompositionNotInitialisedError when empty); `reset()` clears the slot
    (test fixture support only). Lives beside AgentRunner so reads stay
    intra-agent and the agent layer keeps no reverse edge to composition.
    """

    def __init__(self) -> None:
        self._runner: AgentRunner | None = None

    def install(self, runner: AgentRunner) -> None:
        self._runner = runner

    def get(self) -> AgentRunner:
        if self._runner is None:
            raise CompositionNotInitialisedError(
                "AgentRunner not initialised; call build_worker_composition() "
                "or build_api_composition() first"
            )
        return self._runner

    def reset(self) -> None:
        self._runner = None

    @property
    def installed(self) -> bool:
        return self._runner is not None


_global_agent_runner_holder = AgentRunnerHolder()
"""Process-wide AgentRunner holder. Read via get_agent_runner_holder()."""


def get_agent_runner_holder() -> AgentRunnerHolder:
    """Return the process-wide AgentRunnerHolder singleton."""
    return _global_agent_runner_holder
