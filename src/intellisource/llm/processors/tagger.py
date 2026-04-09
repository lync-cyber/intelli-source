"""SemanticTagger: tagging processor using LLM with keyword matching fallback."""

from __future__ import annotations

import json
from typing import Any

from intellisource.llm.processors._async_compat import run_async
from intellisource.llm.prompts import load_prompt
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext


class SemanticTagger(BaseProcessor):
    """Tag content semantically using LLM, with keyword matching fallback."""

    def __init__(
        self,
        gateway: Any,
        call_log: Any,
        tag_library: list[str] | None = None,
    ) -> None:
        self._gateway = gateway
        self._call_log = call_log
        self._tag_library = tag_library or []

    def process(self, context: PipelineContext) -> PipelineContext:
        """Process context to generate semantic tags for body_text.

        Args:
            context: Pipeline context containing body_text and optional title.

        Returns:
            Updated context with tags set.

        Raises:
            ValueError: If body_text key is missing from context.
        """
        body_text = context.get("body_text")
        if body_text is None:
            raise ValueError("body_text is required in context")

        title = context.get("title", "") or ""

        tags = self._try_llm_tagging(body_text, title)
        if tags is None:
            tags = self._keyword_fallback(body_text, title)

        context.set("tags", tags)
        return context

    def _try_llm_tagging(
        self,
        body_text: str,
        title: str,
    ) -> list[str] | None:
        """Attempt LLM-based tagging. Returns None on failure."""
        try:
            library_hint = ""
            if self._tag_library:
                tags_json = json.dumps(self._tag_library, ensure_ascii=False)
                library_hint = f"\nPreferred tags: {tags_json}"
            prompt = load_prompt(
                "tagger",
                library_hint=library_hint,
                title=title,
                body_text=body_text,
            )
            result = run_async(self._gateway.complete(prompt))
            run_async(
                self._call_log.record(
                    call_type="tag",
                    status="success",
                    input_tokens=result.metadata.get("input_tokens", 0),
                    output_tokens=result.metadata.get("output_tokens", 0),
                    metadata=result.metadata,
                )
            )
            parsed = json.loads(result.content)
            if not isinstance(parsed, list):
                return None
            return [str(t) for t in parsed]
        except Exception:
            return None

    def _keyword_fallback(self, body_text: str, title: str) -> list[str]:
        """Fallback: match tags from tag_library by keyword presence in text."""
        combined = body_text + " " + title
        matched = [tag for tag in self._tag_library if tag in combined]
        if not matched:
            return ["未分类"]
        return matched
