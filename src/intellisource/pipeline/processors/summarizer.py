"""LLMSummarizer processor — populates ``ctx['summary']`` via LLM (B-044).

Reads ``title`` and ``body_text`` from the pipeline context, builds a
single-item cluster, and invokes the atomic ``truncate_summary`` tool, which
itself dispatches to ``llm_gateway.complete`` when a gateway is supplied and
falls back to first-3-sentences truncation on any failure or when no gateway
is available.

Failure isolation: every error path resolves to a non-empty string (or the
truncation fallback's empty-string when both title and body are empty), never
raising — pipelines run inside ``asyncio.to_thread(engine.execute, ctx)`` and
a process() exception would otherwise be caught and surfaced as
``ctx['errors']`` by ``PipelineEngine._run_processors``.
"""

from __future__ import annotations

from typing import Any

from intellisource.core.processor import BaseProcessor, PipelineContext
from intellisource.observability.logging import get_logger
from intellisource.pipeline._async_bridge import run_coro
from intellisource.pipeline.processors.tools import truncate_summary

logger = get_logger(__name__)


class _GatewayDeps:
    """Minimal tool_deps stub exposing only the ``llm_gateway`` attribute that
    ``truncate_summary`` inspects via ``getattr``."""

    def __init__(self, llm_gateway: Any) -> None:
        self.llm_gateway = llm_gateway


class LLMSummarizer(BaseProcessor):
    """Pipeline processor that writes ``ctx['summary']`` from an LLM digest."""

    _NEEDS_LLM_GATEWAY: bool = True

    def __init__(self, llm_gateway: Any = None) -> None:
        self._llm_gateway = llm_gateway

    def process(self, context: PipelineContext) -> PipelineContext:
        title = str(context.get("title") or "")
        body_text = str(context.get("body_text") or "")
        cluster = [{"title": title, "body_text": body_text}]
        deps = _GatewayDeps(self._llm_gateway)

        try:
            result = run_coro(truncate_summary(cluster, tool_deps=deps))
        except Exception:
            logger.warning(
                "LLMSummarizer call failed; persisting empty summary",
                exc_info=True,
            )
            context.set("summary", "")
            context.set(
                "digest",
                {"title": title, "summary": "", "timeline": [], "key_points": []},
            )
            return context

        summary = str(result.get("summary", "") or "")
        context.set("summary", summary)
        # Expose the full structured digest so _process_execute can persist
        # timeline / key_points into ProcessedContent.structured_data.
        context.set("digest", result)
        return context
