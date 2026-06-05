"""EmbeddingProcessor — populates ``ctx['embedding']`` via LLM (B-045).

Reads ``body_text`` (and falls back to ``title`` if body is empty) from the
pipeline context, asks ``llm_gateway.embed(text)`` for a vector, and writes
the result back as ``ctx['embedding']``. Persistence into
``ProcessedContent.embedding`` happens in ``_process_execute`` —
this processor only owns the vector-generation step.

Failure isolation: every error path resolves to ``ctx['embedding'] = None``
(graceful degrade so vector search returns zero rows instead of crashing
the whole content-process pipeline when the embedding model has no API
key configured).
"""

from __future__ import annotations

from typing import Any

from intellisource.observability.logging import get_logger
from intellisource.pipeline._async_bridge import run_coro
from intellisource.pipeline.base import BaseProcessor, PipelineContext

logger = get_logger(__name__)


class EmbeddingProcessor(BaseProcessor):
    """Pipeline processor that writes ``ctx['embedding']`` via the LLM gateway."""

    _NEEDS_LLM_GATEWAY: bool = True

    def __init__(self, llm_gateway: Any = None) -> None:
        self._llm_gateway = llm_gateway

    def process(self, context: PipelineContext) -> PipelineContext:
        if self._llm_gateway is None:
            context.set("embedding", None)
            return context

        title = str(context.get("title") or "")
        body_text = str(context.get("body_text") or "")
        text = body_text or title
        if not text.strip():
            context.set("embedding", None)
            return context

        try:
            vec = run_coro(self._llm_gateway.embed(text))
        except Exception:
            logger.warning(
                "EmbeddingProcessor call failed; leaving embedding NULL",
                exc_info=True,
            )
            context.set("embedding", None)
            return context

        if not isinstance(vec, list) or not vec:
            context.set("embedding", None)
            return context

        context.set("embedding", vec)
        return context
