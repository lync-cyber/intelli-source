"""DigestGenerator: summarization processor using LLM with truncation fallback."""

from __future__ import annotations

import json
from typing import Any

from intellisource.llm.processors._async_compat import run_async
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext


class DigestGenerator(BaseProcessor):
    """Generate a comprehensive digest from clustered documents using LLM."""

    def __init__(self, gateway: Any, call_log: Any) -> None:
        self._gateway = gateway
        self._call_log = call_log

    def process(self, context: PipelineContext) -> PipelineContext:
        """Process context to generate a digest from cluster_contents.

        Args:
            context: Pipeline context containing cluster_contents.

        Returns:
            Updated context with digest set.

        Raises:
            ValueError: If cluster_contents key is missing from context.
        """
        cluster_contents = context.get("cluster_contents")
        if cluster_contents is None:
            raise ValueError("cluster_contents is required in context")

        if not cluster_contents:
            context.set(
                "digest",
                {
                    "title": "",
                    "summary": "",
                    "timeline": [],
                    "key_points": [],
                },
            )
            return context

        digest = self._try_llm_digest(cluster_contents)
        if digest is None:
            digest = self._truncation_fallback(cluster_contents)

        context.set("digest", digest)
        return context

    def _try_llm_digest(
        self,
        cluster_contents: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        """Attempt LLM-based digest generation. Returns None on failure."""
        try:
            docs_text = "\n\n".join(
                f"Title: {doc.get('title', '')}\n"
                f"Published: {doc.get('published_at', '')}\n"
                f"Content: {doc.get('body_text', '')}"
                for doc in cluster_contents
            )
            prompt = (
                "Generate a JSON digest for the following clustered documents.\n"
                'Output format: {"title": str, "summary": str, '
                '"timeline": [{"date": str, "event": str}], '
                '"key_points": [str]}\n\n'
                f"{docs_text}"
            )
            result = run_async(self._gateway.complete(prompt))
            run_async(
                self._call_log.record(
                    call_type="summarize",
                    status="success",
                    input_tokens=result.metadata.get("input_tokens", 0),
                    output_tokens=result.metadata.get("output_tokens", 0),
                    metadata=result.metadata,
                )
            )
            parsed = json.loads(result.content)
            if not isinstance(parsed, dict):
                return None
            required = {"title", "summary", "timeline", "key_points"}
            if not required.issubset(set(parsed.keys())):
                return None
            return dict(parsed)
        except Exception:
            return None

    def _truncation_fallback(
        self,
        cluster_contents: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Fallback: build digest from truncated document content."""
        title = cluster_contents[0].get("title", "")
        combined_text = " ".join(doc.get("body_text", "") for doc in cluster_contents)
        sentences = combined_text.split(". ")
        first_sentences = ". ".join(sentences[:3])
        if first_sentences and not first_sentences.endswith("."):
            first_sentences += "."

        return {
            "title": title,
            "summary": first_sentences,
            "timeline": [],
            "key_points": [],
        }
