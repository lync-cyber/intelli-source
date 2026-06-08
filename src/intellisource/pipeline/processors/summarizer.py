"""LLMSummarizer processor — populates ``ctx['summary']`` from a cluster digest.

Reads ``title`` and ``body_text`` from the pipeline context, builds a
single-item cluster, and calls an injected ``summarize_fn`` (bound to the LLM
gateway by ``agent.factory``). When no summarizer is injected it falls back to
first-3-sentence truncation. The LLM path itself lives in
``agent.tools.executes.summarize_cluster`` — the pipeline layer must not import
``intellisource.llm`` (importlinter Contract 2), so the summarizer is injected.

Failure isolation: every error path resolves to a non-empty string (or the
truncation fallback's empty-string when both title and body are empty), never
raising — pipelines run inside ``asyncio.to_thread(engine.execute, ctx)`` and
a process() exception would otherwise be caught and surfaced as
``ctx['errors']`` by ``PipelineEngine._run_processors``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from intellisource.core.processor import BaseProcessor, PipelineContext
from intellisource.observability.logging import get_logger
from intellisource.pipeline._async_bridge import run_coro
from intellisource.pipeline.processors.tools import truncate_fallback

logger = get_logger(__name__)

ClusterSummarizer = Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]]


class LLMSummarizer(BaseProcessor):
    """Pipeline processor that writes ``ctx['summary']`` from a cluster digest."""

    _NEEDS_CLUSTER_SUMMARIZER: bool = True

    def __init__(self, summarize_fn: ClusterSummarizer | None = None) -> None:
        self._summarize_fn = summarize_fn

    def process(self, context: PipelineContext) -> PipelineContext:
        title = str(context.get("title") or "")
        body_text = str(context.get("body_text") or "")
        cluster = [{"title": title, "body_text": body_text}]

        try:
            if self._summarize_fn is not None:
                result = run_coro(self._summarize_fn(cluster))
            else:
                result = truncate_fallback(cluster).model_dump()
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
