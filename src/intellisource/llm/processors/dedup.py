"""SemanticDedup: semantic deduplication processor.

Uses vector search + LLM judgment.
"""

from __future__ import annotations

import json
from typing import Any

from intellisource.llm.processors._async_compat import run_async
from intellisource.llm.processors.fingerprint import FingerprintGenerator
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext


class SemanticDedup(BaseProcessor):
    """Deduplicate content using vector similarity search and LLM judgment."""

    def __init__(
        self,
        gateway: Any,
        vector_store: Any,
        call_log: Any,
        similarity_threshold: float = 0.85,
    ) -> None:
        self._gateway = gateway
        self._vector_store = vector_store
        self._call_log = call_log
        self.similarity_threshold = similarity_threshold
        self._fingerprint_gen = FingerprintGenerator()

    def process(self, context: PipelineContext) -> PipelineContext:
        """Run the dedup flow: fingerprint -> vector search -> LLM judge."""
        title = context.get("title")
        body_text = context.get("body_text")
        embedding = context.get("embedding")

        # Always generate fingerprint
        fp = self._fingerprint_gen.generate(title or "", body_text or "")
        context.set("fingerprint", fp)

        try:
            candidates = self._vector_store.search_similar(
                embedding, threshold=self.similarity_threshold
            )
        except Exception:
            context.set("dedup_fallback", True)
            context.set("dedup_method", "simhash")
            return context

        if candidates:
            try:
                self._judge_with_llm(context, title, body_text, candidates)
            except Exception:
                context.set("dedup_fallback", True)
                context.set("dedup_method", "simhash")

        return context

    def _judge_with_llm(
        self,
        context: PipelineContext,
        title: str | None,
        body_text: str | None,
        candidates: list[Any],
    ) -> None:
        """Call LLM to judge whether the content is a duplicate of candidates."""
        candidate_info = "\n".join(
            f"- ID: {c.id}, Score: {c.score}, Title: {c.title}, Body: {c.body_text}"
            for c in candidates
        )
        prompt = (
            f"Determine if the following content is a duplicate of any candidate.\n\n"
            f"New content:\nTitle: {title}\nBody: {body_text}\n\n"
            f"Candidates:\n{candidate_info}\n\n"
            f'Respond with JSON: {{"is_duplicate": bool, "confidence": float}}'
        )
        result = run_async(self._gateway.complete(prompt))
        run_async(
            self._call_log.record(
                call_type="dedup",
                status="success",
                input_tokens=result.metadata.get("input_tokens", 0),
                output_tokens=result.metadata.get("output_tokens", 0),
                metadata=result.metadata,
            )
        )
        parsed = json.loads(result.content)
        if parsed.get("is_duplicate"):
            context.set("is_duplicate", True)
