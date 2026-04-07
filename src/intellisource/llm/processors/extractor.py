"""LLMExtractor: structured data extraction processor using LLM with regex fallback."""

from __future__ import annotations

import json
import re
from typing import Any

import jsonschema

from intellisource.llm.processors._async_compat import run_async
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext


class LLMExtractor(BaseProcessor):
    """Extract structured data from text using LLM, with regex fallback."""

    def __init__(
        self,
        gateway: Any,
        call_log: Any,
        extraction_schema: dict[str, Any],
    ) -> None:
        self._gateway = gateway
        self._call_log = call_log
        self._extraction_schema = extraction_schema

    def process(self, context: PipelineContext) -> PipelineContext:
        """Process context to extract structured data.

        Args:
            context: Pipeline context containing body_text.

        Returns:
            Updated context with structured_data set.

        Raises:
            ValueError: If body_text key is missing from context.
        """
        body_text = context.get("body_text")
        if body_text is None:
            raise ValueError("body_text is required in context")

        traditional_parse_failed = context.get("traditional_parse_failed", False)

        if traditional_parse_failed:
            structured = self._try_llm_extraction(body_text)
            if structured is None:
                structured = self._regex_fallback(body_text)
            context.set("structured_data", structured)

        return context

    def _try_llm_extraction(self, body_text: str) -> dict[str, Any] | None:
        """Attempt LLM-based extraction. Returns None on failure."""
        try:
            prompt = (
                f"Extract structured data from the following text as JSON.\n"
                f"Schema: {json.dumps(self._extraction_schema)}\n\n"
                f"Text:\n{body_text}"
            )
            result = run_async(self._gateway.complete(prompt))
            parsed = json.loads(result.content)
            jsonschema.validate(instance=parsed, schema=self._extraction_schema)
            run_async(
                self._call_log.record(
                    call_type="extract",
                    status="success",
                    input_tokens=result.metadata.get("input_tokens", 0),
                    output_tokens=result.metadata.get("output_tokens", 0),
                    metadata=result.metadata,
                )
            )
            return dict(parsed)
        except Exception:
            run_async(
                self._call_log.record(
                    call_type="extract",
                    status="fallback",
                    input_tokens=0,
                )
            )
            return None

    # Mapping from field name to (regex pattern, is_list).
    _REGEX_PATTERNS: list[tuple[str, re.Pattern[str], bool]] = [
        ("title", re.compile(r"Title:\s*(.+)"), False),
        ("authors", re.compile(r"Authors:\s*(.+)"), True),
        ("keywords", re.compile(r"Keywords:\s*(.+)"), True),
        ("date", re.compile(r"Date:\s*(.+)"), False),
    ]

    def _regex_fallback(self, body_text: str) -> dict[str, Any]:
        """Extract structured data using regex patterns."""
        result: dict[str, Any] = {}
        for field, pattern, is_list in self._REGEX_PATTERNS:
            match = pattern.search(body_text)
            if match:
                value = match.group(1).strip()
                result[field] = (
                    [item.strip() for item in value.split(",")] if is_list else value
                )
        return result
