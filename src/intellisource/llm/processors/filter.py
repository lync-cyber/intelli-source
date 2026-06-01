"""Sensitive word filtering and compliance check processor."""

from __future__ import annotations

import json

from intellisource.core.encoding import read_text
from intellisource.core.processor import BaseProcessor, PipelineContext


class ContentFilter(BaseProcessor):
    """Filters text for sensitive words and flags matches for human review."""

    def __init__(
        self,
        sensitive_words: list[str] | None = None,
        config_path: str | None = None,
    ) -> None:
        self._words: list[str] = list(sensitive_words) if sensitive_words else []
        self._config_path: str | None = config_path
        if config_path is not None:
            self.load_words(config_path)

    def load_words(self, config_path: str) -> None:
        """Load sensitive words from a JSON config file."""
        self._config_path = config_path
        data = json.loads(read_text(config_path))
        self._words = list(data.get("sensitive_words", []))

    def reload_words(self) -> None:
        """Re-read the config file to pick up changes."""
        if self._config_path is not None:
            self.load_words(self._config_path)

    def _find_matches(self, text: str) -> list[str]:
        """Return deduplicated list of sensitive words found in text."""
        if not text:
            return []
        text_lower = text.lower()
        return [w for w in self._words if w.lower() in text_lower]

    def filter_input(self, text: str) -> tuple[str, list[str]]:
        """Check input text for sensitive words. Returns (original_text, matched)."""
        return text, self._find_matches(text)

    def filter_output(self, text: str) -> tuple[str, list[str]]:
        """Check output text for sensitive words. Returns (original_text, matched)."""
        return text, self._find_matches(text)

    def process(self, context: PipelineContext) -> PipelineContext:
        """Process context: check body_text and llm_output for sensitive words."""
        all_matched: list[str] = []

        body_text = context.get("body_text", "")
        if body_text:
            _, matched = self.filter_input(body_text)
            all_matched.extend(matched)

        llm_output = context.get("llm_output")
        if llm_output is not None:
            _, matched = self.filter_output(llm_output)
            for w in matched:
                if w not in all_matched:
                    all_matched.append(w)

        if all_matched:
            context.set("needs_review", True)
            context.set("matched_sensitive_words", all_matched)

        return context
