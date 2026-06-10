"""LoopObserver — the lifecycle-event sink the agent executors emit through.

The strict / flexible / batch executors report pipeline, tool and llm events to
a single observer instead of four separately injected callables. The default
implementation persists via a ``PipelineEventLogger``; a ``None`` logger makes
every event a no-op so a runner assembled without observability still drives.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from intellisource.agent.events import PipelineEventLogger


@runtime_checkable
class LoopObserver(Protocol):
    """Sink for agent-loop lifecycle events."""

    async def pipeline_start(
        self, pipeline_name: str, chain_id: str, mode: str
    ) -> None: ...

    async def tool_call(
        self,
        pipeline_name: str,
        chain_id: str,
        tool_name: str,
        duration_ms: float,
        status: str,
        error: str | None = None,
    ) -> None: ...

    async def llm_call(
        self,
        pipeline_name: str,
        chain_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> None: ...

    async def pipeline_error(
        self, pipeline_name: str, chain_id: str, error: str
    ) -> None: ...


class PipelineLoopObserver:
    """LoopObserver that persists events through a ``PipelineEventLogger``.

    A ``None`` logger makes every method a no-op, so the loops run unchanged when
    no event log is wired (the silent path the runtime falls back to in tests and
    in compositions assembled without observability).
    """

    def __init__(self, event_logger: PipelineEventLogger | None = None) -> None:
        self._event_logger = event_logger

    async def pipeline_start(
        self, pipeline_name: str, chain_id: str, mode: str
    ) -> None:
        if self._event_logger is None:
            return
        await self._event_logger.pipeline_start(
            pipeline_name=pipeline_name,
            task_chain_id=chain_id,
            mode=mode,
        )

    async def tool_call(
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

    async def llm_call(
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

    async def pipeline_error(
        self, pipeline_name: str, chain_id: str, error: str
    ) -> None:
        if self._event_logger is None:
            return
        await self._event_logger.pipeline_error(
            pipeline_name=pipeline_name,
            task_chain_id=chain_id,
            error=error,
        )
