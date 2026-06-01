"""PipelineEventLogger: structured runtime event log for AgentRunner.

Appends JSONL records to `pipeline-events.jsonl` covering pipeline_start,
tool_call, llm_call, pipeline_complete and pipeline_error. Write failures
are logged at WARNING and never propagate to the calling pipeline.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from intellisource.core.encoding import ENCODING
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

EventType = Literal[
    "pipeline_start",
    "tool_call",
    "llm_call",
    "pipeline_complete",
    "pipeline_error",
]

_DEFAULT_PATH = Path("pipeline-events.jsonl")


class PipelineEventLogger:
    """Append structured runtime events to a JSONL file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else _DEFAULT_PATH

    @property
    def path(self) -> Path:
        return self._path

    async def log(
        self,
        *,
        event: EventType,
        pipeline_name: str,
        task_chain_id: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Append one event record. Never raises — write errors warn-and-drop."""
        record: dict[str, Any] = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "event": event,
            "pipeline_name": pipeline_name,
            "task_chain_id": task_chain_id,
            "detail": detail or {},
        }
        line = json.dumps(record, default=str, ensure_ascii=False) + "\n"
        try:
            await asyncio.to_thread(self._append, line)
        except Exception as exc:
            logger.warning(
                "pipeline_events: write failed for event=%s pipeline=%s: %s",
                event,
                pipeline_name,
                exc,
            )

    def _append(self, line: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding=ENCODING) as fh:
            fh.write(line)

    async def pipeline_start(
        self,
        *,
        pipeline_name: str,
        task_chain_id: str,
        mode: str,
    ) -> None:
        await self.log(
            event="pipeline_start",
            pipeline_name=pipeline_name,
            task_chain_id=task_chain_id,
            detail={"mode": mode},
        )

    async def tool_call(
        self,
        *,
        pipeline_name: str,
        task_chain_id: str,
        tool_name: str,
        duration_ms: float,
        status: Literal["success", "error"],
        error: str | None = None,
    ) -> None:
        detail: dict[str, Any] = {
            "tool_name": tool_name,
            "duration_ms": duration_ms,
            "status": status,
        }
        if error is not None:
            detail["error"] = error
        await self.log(
            event="tool_call",
            pipeline_name=pipeline_name,
            task_chain_id=task_chain_id,
            detail=detail,
        )

    async def llm_call(
        self,
        *,
        pipeline_name: str,
        task_chain_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> None:
        await self.log(
            event="llm_call",
            pipeline_name=pipeline_name,
            task_chain_id=task_chain_id,
            detail={
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
            },
        )

    async def pipeline_complete(
        self,
        *,
        pipeline_name: str,
        task_chain_id: str,
        status: str,
        steps_executed: int,
    ) -> None:
        await self.log(
            event="pipeline_complete",
            pipeline_name=pipeline_name,
            task_chain_id=task_chain_id,
            detail={"status": status, "steps_executed": steps_executed},
        )

    async def pipeline_error(
        self,
        *,
        pipeline_name: str,
        task_chain_id: str,
        error: str,
    ) -> None:
        await self.log(
            event="pipeline_error",
            pipeline_name=pipeline_name,
            task_chain_id=task_chain_id,
            detail={"error": error},
        )
