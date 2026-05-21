"""Tests for ContentFilter (T-026: sensitive word filtering and compliance check).

Covers:
- AC-T026-1: ContentFilter implements BaseProcessor interface
- AC-T026-2: Sensitive word library loadable from config file with hot-reload
- AC-T026-3: Filter input text before LLM call
- AC-T026-4: Filter LLM output (secondary check)
- AC-T026-5: Matched content marked for human review (not auto-discarded)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intellisource.llm.processors.filter import ContentFilter
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SENSITIVE_WORDS = ["confidential", "top-secret", "classified"]

CLEAN_TEXT = "This is a normal article about open-source software development."

TEXT_WITH_SENSITIVE = (
    "This document contains confidential information about the project."
)

TEXT_WITH_MULTIPLE = (
    "This top-secret report has classified data and confidential notes."
)

LLM_OUTPUT_CLEAN = "The analysis shows positive growth trends in the market."

LLM_OUTPUT_SENSITIVE = (
    "The analysis reveals classified details about internal operations."
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sensitive_words() -> list[str]:
    return SENSITIVE_WORDS.copy()


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """Create a temporary config file with sensitive words."""
    config = tmp_path / "sensitive_words.json"
    config.write_text(json.dumps({"sensitive_words": SENSITIVE_WORDS}))
    return config


@pytest.fixture
def filter_with_words(sensitive_words: list[str]) -> ContentFilter:
    """ContentFilter initialized with an explicit word list."""
    return ContentFilter(sensitive_words=sensitive_words)


@pytest.fixture
def clean_context() -> PipelineContext:
    """PipelineContext with clean body_text (no sensitive words)."""
    ctx = PipelineContext()
    ctx.set("body_text", CLEAN_TEXT)
    return ctx


@pytest.fixture
def sensitive_context() -> PipelineContext:
    """PipelineContext with body_text containing sensitive words."""
    ctx = PipelineContext()
    ctx.set("body_text", TEXT_WITH_SENSITIVE)
    return ctx


@pytest.fixture
def context_with_llm_output() -> PipelineContext:
    """PipelineContext with both body_text and llm_output."""
    ctx = PipelineContext()
    ctx.set("body_text", CLEAN_TEXT)
    ctx.set("llm_output", LLM_OUTPUT_SENSITIVE)
    return ctx


# ---------------------------------------------------------------------------
# AC-T026-1: ContentFilter implements BaseProcessor interface
# ---------------------------------------------------------------------------


class TestContentFilterInterface:
    """AC-T026-1: ContentFilter must implement the BaseProcessor interface."""

    def test_is_subclass_of_base_processor(self) -> None:
        """ContentFilter must be a subclass of BaseProcessor."""
        assert issubclass(ContentFilter, BaseProcessor)

    def test_instance_is_base_processor(self, filter_with_words: ContentFilter) -> None:
        """ContentFilter instance must be an instance of BaseProcessor."""
        assert isinstance(filter_with_words, BaseProcessor)

    def test_has_process_method(self, filter_with_words: ContentFilter) -> None:
        """ContentFilter must have a callable process method."""
        assert callable(getattr(filter_with_words, "process", None))

    def test_process_returns_pipeline_context(
        self, filter_with_words: ContentFilter, clean_context: PipelineContext
    ) -> None:
        """process() must accept PipelineContext and return PipelineContext."""
        result = filter_with_words.process(clean_context)
        assert isinstance(result, PipelineContext)


# ---------------------------------------------------------------------------
# AC-T026-2: Sensitive word library from config file + hot-reload
# ---------------------------------------------------------------------------


class TestSensitiveWordLoading:
    """AC-T026-2: Sensitive word library loadable from config and hot-reloadable."""

    def test_load_words_from_config_file(self, config_file: Path) -> None:
        """load_words() must load sensitive words from a JSON config file."""
        cf = ContentFilter(config_path=str(config_file))
        # After construction with config_path, words should be loaded
        _, matched = cf.filter_input(TEXT_WITH_SENSITIVE)
        assert len(matched) > 0
        assert "confidential" in [w.lower() for w in matched]

    def test_load_words_method(self, config_file: Path) -> None:
        """load_words(path) must populate the internal sensitive word list."""
        cf = ContentFilter()
        cf.load_words(str(config_file))
        _, matched = cf.filter_input(TEXT_WITH_SENSITIVE)
        assert len(matched) > 0

    def test_reload_words_picks_up_changes(self, config_file: Path) -> None:
        """reload_words() must re-read the config file to pick up changes."""
        cf = ContentFilter(config_path=str(config_file))

        # Initially "forbidden" is not in the word list
        _, matched_before = cf.filter_input("This is forbidden content.")
        assert "forbidden" not in [w.lower() for w in matched_before]

        # Update the config file to add "forbidden"
        updated_words = SENSITIVE_WORDS + ["forbidden"]
        config_file.write_text(json.dumps({"sensitive_words": updated_words}))

        # Hot-reload
        cf.reload_words()

        # Now "forbidden" should be detected
        _, matched_after = cf.filter_input("This is forbidden content.")
        assert "forbidden" in [w.lower() for w in matched_after]

    def test_constructor_with_explicit_words(self) -> None:
        """Constructor with sensitive_words list must use those words directly."""
        cf = ContentFilter(sensitive_words=["secret"])
        _, matched = cf.filter_input("This is a secret message.")
        assert "secret" in [w.lower() for w in matched]

    def test_constructor_no_args_has_empty_words(self) -> None:
        """Constructor with no arguments should have an empty word list."""
        cf = ContentFilter()
        _, matched = cf.filter_input(TEXT_WITH_SENSITIVE)
        assert matched == []


# ---------------------------------------------------------------------------
# AC-T026-3: Filter input text before LLM call
# ---------------------------------------------------------------------------


class TestInputFiltering:
    """AC-T026-3: LLM input must be filtered for sensitive information."""

    def test_filter_input_detects_sensitive_word(
        self, filter_with_words: ContentFilter
    ) -> None:
        """filter_input() must detect sensitive words in text."""
        _, matched = filter_with_words.filter_input(TEXT_WITH_SENSITIVE)
        assert "confidential" in [w.lower() for w in matched]

    def test_filter_input_returns_tuple(self, filter_with_words: ContentFilter) -> None:
        """filter_input() must return a tuple of (text, matched_words)."""
        result = filter_with_words.filter_input(TEXT_WITH_SENSITIVE)
        assert isinstance(result, tuple)
        assert len(result) == 2
        filtered_text, matched_words = result
        assert isinstance(filtered_text, str)
        assert isinstance(matched_words, list)

    def test_filter_input_case_insensitive(
        self, filter_with_words: ContentFilter
    ) -> None:
        """Sensitive word matching must be case-insensitive."""
        text_upper = "This is CONFIDENTIAL information."
        _, matched = filter_with_words.filter_input(text_upper)
        assert len(matched) > 0

    def test_filter_input_detects_multiple_words(
        self, filter_with_words: ContentFilter
    ) -> None:
        """filter_input() must detect all matching sensitive words."""
        _, matched = filter_with_words.filter_input(TEXT_WITH_MULTIPLE)
        matched_lower = [w.lower() for w in matched]
        assert "confidential" in matched_lower
        assert "top-secret" in matched_lower
        assert "classified" in matched_lower

    def test_filter_input_clean_text_returns_empty_matches(
        self, filter_with_words: ContentFilter
    ) -> None:
        """filter_input() on clean text must return an empty match list."""
        _, matched = filter_with_words.filter_input(CLEAN_TEXT)
        assert matched == []

    def test_process_filters_body_text(
        self, filter_with_words: ContentFilter, sensitive_context: PipelineContext
    ) -> None:
        """process() must filter body_text from context and set matched words."""
        result = filter_with_words.process(sensitive_context)
        matched = result.get("matched_sensitive_words")
        assert matched is not None
        assert isinstance(matched, list)
        assert len(matched) > 0

    def test_filter_input_empty_text(self, filter_with_words: ContentFilter) -> None:
        """filter_input() with empty string must return empty matches."""
        _, matched = filter_with_words.filter_input("")
        assert matched == []


# ---------------------------------------------------------------------------
# AC-T026-4: Filter LLM output (secondary check)
# ---------------------------------------------------------------------------


class TestOutputFiltering:
    """AC-T026-4: LLM output must be checked for sensitive content."""

    def test_filter_output_detects_sensitive_word(
        self, filter_with_words: ContentFilter
    ) -> None:
        """filter_output() must detect sensitive words in LLM output."""
        _, matched = filter_with_words.filter_output(LLM_OUTPUT_SENSITIVE)
        assert "classified" in [w.lower() for w in matched]

    def test_filter_output_returns_tuple(
        self, filter_with_words: ContentFilter
    ) -> None:
        """filter_output() must return a tuple of (text, matched_words)."""
        result = filter_with_words.filter_output(LLM_OUTPUT_SENSITIVE)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_filter_output_clean_text(self, filter_with_words: ContentFilter) -> None:
        """filter_output() on clean LLM output must return empty matches."""
        _, matched = filter_with_words.filter_output(LLM_OUTPUT_CLEAN)
        assert matched == []

    def test_process_checks_llm_output(
        self, filter_with_words: ContentFilter, context_with_llm_output: PipelineContext
    ) -> None:
        """process() must also check llm_output if present in context."""
        result = filter_with_words.process(context_with_llm_output)
        matched = result.get("matched_sensitive_words")
        assert matched is not None
        assert len(matched) > 0
        assert "classified" in [w.lower() for w in matched]

    def test_process_no_llm_output_only_checks_input(
        self, filter_with_words: ContentFilter, sensitive_context: PipelineContext
    ) -> None:
        """When llm_output is absent, process() checks only body_text."""
        result = filter_with_words.process(sensitive_context)
        # Should still find sensitive words in body_text
        matched = result.get("matched_sensitive_words")
        assert matched is not None
        assert len(matched) > 0


# ---------------------------------------------------------------------------
# AC-T026-5: Matched content marked for human review (not auto-discarded)
# ---------------------------------------------------------------------------


class TestHumanReviewMarking:
    """AC-T026-5: Sensitive matches must be flagged for review, not discarded."""

    def test_needs_review_set_true_on_match(
        self, filter_with_words: ContentFilter, sensitive_context: PipelineContext
    ) -> None:
        """process() must set needs_review=True when sensitive words are found."""
        result = filter_with_words.process(sensitive_context)
        assert result.get("needs_review") is True

    def test_needs_review_not_set_on_clean(
        self, filter_with_words: ContentFilter, clean_context: PipelineContext
    ) -> None:
        """process() must NOT set needs_review=True when no sensitive words found."""
        result = filter_with_words.process(clean_context)
        needs_review = result.get("needs_review")
        assert needs_review is None or needs_review is False

    def test_original_text_preserved(
        self, filter_with_words: ContentFilter, sensitive_context: PipelineContext
    ) -> None:
        """process() must preserve the original body_text (mark, not discard)."""
        original_text = sensitive_context.get("body_text")
        result = filter_with_words.process(sensitive_context)
        assert result.get("body_text") == original_text

    def test_matched_words_list_populated(
        self, filter_with_words: ContentFilter, sensitive_context: PipelineContext
    ) -> None:
        """process() must set matched_sensitive_words with the list of matches."""
        result = filter_with_words.process(sensitive_context)
        matched = result.get("matched_sensitive_words")
        assert isinstance(matched, list)
        assert len(matched) > 0

    def test_needs_review_on_llm_output_match(
        self, filter_with_words: ContentFilter, context_with_llm_output: PipelineContext
    ) -> None:
        """needs_review must be True when sensitive words found in llm_output."""
        result = filter_with_words.process(context_with_llm_output)
        assert result.get("needs_review") is True

    def test_llm_output_preserved_on_match(
        self, filter_with_words: ContentFilter, context_with_llm_output: PipelineContext
    ) -> None:
        """LLM output must be preserved (marked, not discarded) even with matches."""
        original_output = context_with_llm_output.get("llm_output")
        result = filter_with_words.process(context_with_llm_output)
        assert result.get("llm_output") == original_output


# ---------------------------------------------------------------------------
# Edge cases / boundary conditions
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary conditions for ContentFilter."""

    def test_filter_input_with_none_text(
        self, filter_with_words: ContentFilter
    ) -> None:
        """filter_input(None-like empty) should handle gracefully."""
        _, matched = filter_with_words.filter_input("")
        assert matched == []

    def test_sensitive_word_substring_match(
        self, filter_with_words: ContentFilter
    ) -> None:
        """Sensitive word 'confidential' should be detected even within a sentence."""
        text = "Theconfidentialreport was leaked."
        _, matched = filter_with_words.filter_input(text)
        # String-contains check should still match
        assert "confidential" in [w.lower() for w in matched]

    def test_multiple_occurrences_of_same_word(
        self, filter_with_words: ContentFilter
    ) -> None:
        """Same sensitive word appearing multiple times should appear in matches."""
        text = "confidential data and more confidential info"
        _, matched = filter_with_words.filter_input(text)
        matched_lower = [w.lower() for w in matched]
        assert "confidential" in matched_lower
