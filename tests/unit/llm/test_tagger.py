"""Tests for SemanticTagger tagging processor.

Covers:
- AC-024: SemanticTagger uses semantics to tag content; unclassifiable -> "未分类"
- AC-025: All processors support degradation to traditional logic
- AC-T025-2: Tagging degradation uses keyword matching + predefined tag library
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from intellisource.llm.processors.tagger import SemanticTagger

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_BODY_TEXT = (
    "Machine learning models are transforming healthcare diagnostics. "
    "Deep neural networks achieve state-of-the-art accuracy on imaging tasks. "
    "Clinical deployment requires rigorous validation protocols."
)

SAMPLE_TAG_LIBRARY: list[str] = [
    "人工智能",
    "医疗健康",
    "深度学习",
    "自然语言处理",
    "计算机视觉",
    "金融科技",
    "网络安全",
]

SAMPLE_LLM_TAGS_OUTPUT = json.dumps(["人工智能", "医疗健康", "深度学习"])

SAMPLE_LLM_UNCLASSIFIABLE_OUTPUT = json.dumps(["未分类"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gateway() -> AsyncMock:
    """Create a mock LLMGateway that returns valid tag JSON."""
    gateway = AsyncMock()
    result = MagicMock()
    result.content = SAMPLE_LLM_TAGS_OUTPUT
    result.metadata = {
        "input_tokens": 200,
        "output_tokens": 30,
        "latency_ms": 400.0,
        "model": "gpt-4o-mini",
    }
    gateway.complete = AsyncMock(return_value=result)
    return gateway


@pytest.fixture
def mock_gateway_failing() -> AsyncMock:
    """Create a mock LLMGateway that always raises an error."""
    gateway = AsyncMock()
    gateway.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    return gateway


@pytest.fixture
def mock_gateway_unclassifiable() -> AsyncMock:
    """Create a mock LLMGateway that returns unclassifiable result."""
    gateway = AsyncMock()
    result = MagicMock()
    result.content = SAMPLE_LLM_UNCLASSIFIABLE_OUTPUT
    result.metadata = {
        "input_tokens": 200,
        "output_tokens": 10,
        "latency_ms": 300.0,
        "model": "gpt-4o-mini",
    }
    gateway.complete = AsyncMock(return_value=result)
    return gateway


@pytest.fixture
def mock_call_log() -> AsyncMock:
    """Create a mock LLMCallLog recorder."""
    return AsyncMock()


@pytest.fixture
def pipeline_context() -> PipelineContext:
    """Create a PipelineContext with sample body text and title."""
    ctx = PipelineContext()
    ctx.set("body_text", SAMPLE_BODY_TEXT)
    ctx.set("title", "AI in Healthcare Diagnostics")
    return ctx


@pytest.fixture
def semantic_tagger(
    mock_gateway: AsyncMock,
    mock_call_log: AsyncMock,
) -> SemanticTagger:
    """Create a SemanticTagger with mocked dependencies and tag library."""
    return SemanticTagger(
        gateway=mock_gateway,
        call_log=mock_call_log,
        tag_library=SAMPLE_TAG_LIBRARY,
    )


# ---------------------------------------------------------------------------
# SemanticTagger implements BaseProcessor
# ---------------------------------------------------------------------------


class TestSemanticTaggerInterface:
    """Verify SemanticTagger satisfies the BaseProcessor contract."""

    def test_is_subclass_of_base_processor(self) -> None:
        """SemanticTagger must be a subclass of BaseProcessor."""
        assert issubclass(SemanticTagger, BaseProcessor)

    def test_has_process_method(self, semantic_tagger: SemanticTagger) -> None:
        """SemanticTagger instance must expose a callable process method."""
        assert callable(getattr(semantic_tagger, "process", None))

    def test_process_accepts_pipeline_context(
        self, semantic_tagger: SemanticTagger
    ) -> None:
        """process() signature must include a 'context' parameter."""
        import inspect

        sig = inspect.signature(semantic_tagger.process)
        params = list(sig.parameters.keys())
        assert "context" in params

    def test_process_returns_pipeline_context(
        self,
        semantic_tagger: SemanticTagger,
        pipeline_context: PipelineContext,
    ) -> None:
        """process() must return a PipelineContext instance."""
        result = semantic_tagger.process(pipeline_context)
        assert isinstance(result, PipelineContext)


# ---------------------------------------------------------------------------
# AC-024: Semantic tagging with LLM
# ---------------------------------------------------------------------------


class TestSemanticTagging:
    """Verify LLM-based semantic tagging for content."""

    def test_llm_called_for_tagging(
        self,
        semantic_tagger: SemanticTagger,
        pipeline_context: PipelineContext,
        mock_gateway: AsyncMock,
    ) -> None:
        """process() must invoke the LLM gateway to generate tags."""
        semantic_tagger.process(pipeline_context)
        mock_gateway.complete.assert_called_once()

    def test_tags_set_in_context(
        self,
        semantic_tagger: SemanticTagger,
        pipeline_context: PipelineContext,
    ) -> None:
        """process() must store the tags under the 'tags' key in context."""
        result_ctx = semantic_tagger.process(pipeline_context)
        tags = result_ctx.get("tags")
        assert tags is not None
        assert isinstance(tags, list)

    def test_tags_are_strings(
        self,
        semantic_tagger: SemanticTagger,
        pipeline_context: PipelineContext,
    ) -> None:
        """Each tag in the tags list must be a string."""
        result_ctx = semantic_tagger.process(pipeline_context)
        tags = result_ctx.get("tags")
        assert tags is not None
        for tag in tags:
            assert isinstance(tag, str)

    def test_tags_are_non_empty(
        self,
        semantic_tagger: SemanticTagger,
        pipeline_context: PipelineContext,
    ) -> None:
        """The tags list should contain at least one tag."""
        result_ctx = semantic_tagger.process(pipeline_context)
        tags = result_ctx.get("tags")
        assert tags is not None
        assert len(tags) > 0

    def test_tags_preserves_existing_context_keys(
        self,
        semantic_tagger: SemanticTagger,
        pipeline_context: PipelineContext,
    ) -> None:
        """Tagging must not clobber pre-existing context keys."""
        pipeline_context.set("source_id", "doc-001")
        result_ctx = semantic_tagger.process(pipeline_context)
        assert result_ctx.get("source_id") == "doc-001"
        assert result_ctx.get("body_text") == SAMPLE_BODY_TEXT


# ---------------------------------------------------------------------------
# AC-024: Unclassifiable content -> "未分类"
# ---------------------------------------------------------------------------


class TestUnclassifiableContent:
    """Verify that unclassifiable content gets tagged with '未分类'."""

    def test_unclassifiable_returns_wei_fen_lei_tag(
        self,
        mock_gateway_unclassifiable: AsyncMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """When LLM cannot classify, tags should contain '未分类'."""
        tagger = SemanticTagger(
            gateway=mock_gateway_unclassifiable,
            call_log=mock_call_log,
            tag_library=SAMPLE_TAG_LIBRARY,
        )
        result_ctx = tagger.process(pipeline_context)
        tags = result_ctx.get("tags")
        assert tags is not None
        assert "未分类" in tags

    def test_unclassifiable_with_gibberish_body(
        self,
        mock_gateway_unclassifiable: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """Content that is pure gibberish should result in '未分类' tag."""
        ctx = PipelineContext()
        ctx.set("body_text", "asdf jkl; qwerty zxcv bnm")
        ctx.set("title", "Unknown")
        tagger = SemanticTagger(
            gateway=mock_gateway_unclassifiable,
            call_log=mock_call_log,
            tag_library=SAMPLE_TAG_LIBRARY,
        )
        result_ctx = tagger.process(ctx)
        tags = result_ctx.get("tags")
        assert tags is not None
        assert "未分类" in tags


# ---------------------------------------------------------------------------
# AC-025 + AC-T025-2: Degradation to keyword matching + predefined tag library
# ---------------------------------------------------------------------------


class TestTaggerDegradation:
    """Verify fallback to keyword matching when LLM fails."""

    def test_degrade_on_llm_exception(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """When LLM raises an exception, process() must not raise and must produce tags."""
        tagger = SemanticTagger(
            gateway=mock_gateway_failing,
            call_log=mock_call_log,
            tag_library=SAMPLE_TAG_LIBRARY,
        )
        result_ctx = tagger.process(pipeline_context)
        tags = result_ctx.get("tags")
        assert tags is not None
        assert isinstance(tags, list)

    def test_degraded_tags_come_from_tag_library(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """Degraded tags must come from the predefined tag library via keyword matching."""
        ctx = PipelineContext()
        ctx.set("body_text", "深度学习在医疗健康领域的应用越来越广泛。")
        ctx.set("title", "深度学习医疗应用")
        tagger = SemanticTagger(
            gateway=mock_gateway_failing,
            call_log=mock_call_log,
            tag_library=SAMPLE_TAG_LIBRARY,
        )
        result_ctx = tagger.process(ctx)
        tags = result_ctx.get("tags")
        assert tags is not None
        # All degraded tags must exist in the tag library or be "未分类"
        for tag in tags:
            assert tag in SAMPLE_TAG_LIBRARY or tag == "未分类"

    def test_degraded_keyword_match_finds_relevant_tags(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """Keyword matching should find tags whose keywords appear in the text."""
        ctx = PipelineContext()
        ctx.set("body_text", "深度学习模型在医疗健康诊断中发挥重要作用。")
        ctx.set("title", "深度学习诊断")
        tagger = SemanticTagger(
            gateway=mock_gateway_failing,
            call_log=mock_call_log,
            tag_library=SAMPLE_TAG_LIBRARY,
        )
        result_ctx = tagger.process(ctx)
        tags = result_ctx.get("tags")
        assert tags is not None
        assert len(tags) > 0
        # Should match at least "深度学习" since keyword appears in text
        assert "深度学习" in tags

    def test_degraded_no_match_yields_unclassified(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """When no keywords match from library, degraded result should contain '未分类'."""
        ctx = PipelineContext()
        ctx.set("body_text", "The quick brown fox jumps over the lazy dog.")
        ctx.set("title", "Pangram Example")
        tagger = SemanticTagger(
            gateway=mock_gateway_failing,
            call_log=mock_call_log,
            tag_library=SAMPLE_TAG_LIBRARY,
        )
        result_ctx = tagger.process(ctx)
        tags = result_ctx.get("tags")
        assert tags is not None
        assert "未分类" in tags

    def test_degraded_does_not_retry_llm(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """Once LLM fails, degradation must not make additional LLM calls."""
        tagger = SemanticTagger(
            gateway=mock_gateway_failing,
            call_log=mock_call_log,
            tag_library=SAMPLE_TAG_LIBRARY,
        )
        tagger.process(pipeline_context)
        assert mock_gateway_failing.complete.call_count == 1

    def test_degrade_on_invalid_json_response(
        self,
        mock_call_log: AsyncMock,
        pipeline_context: PipelineContext,
    ) -> None:
        """When LLM returns non-JSON, degrade to keyword matching."""
        gateway = AsyncMock()
        bad_result = MagicMock()
        bad_result.content = "This is not valid JSON"
        bad_result.metadata = {
            "input_tokens": 100,
            "output_tokens": 20,
            "latency_ms": 150.0,
            "model": "gpt-4o-mini",
        }
        gateway.complete = AsyncMock(return_value=bad_result)

        tagger = SemanticTagger(
            gateway=gateway,
            call_log=mock_call_log,
            tag_library=SAMPLE_TAG_LIBRARY,
        )
        result_ctx = tagger.process(pipeline_context)
        tags = result_ctx.get("tags")
        assert tags is not None
        assert isinstance(tags, list)


# ---------------------------------------------------------------------------
# Constructor with optional tag_library
# ---------------------------------------------------------------------------


class TestTaggerConstruction:
    """Verify SemanticTagger constructor handles optional tag_library."""

    def test_construct_without_tag_library(
        self,
        mock_gateway: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """SemanticTagger should accept tag_library=None (default)."""
        tagger = SemanticTagger(
            gateway=mock_gateway,
            call_log=mock_call_log,
        )
        assert tagger is not None

    def test_construct_with_empty_tag_library(
        self,
        mock_gateway: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        """SemanticTagger should accept an empty tag library."""
        tagger = SemanticTagger(
            gateway=mock_gateway,
            call_log=mock_call_log,
            tag_library=[],
        )
        assert tagger is not None


# ---------------------------------------------------------------------------
# Edge cases / boundary conditions
# ---------------------------------------------------------------------------


class TestTaggerEdgeCases:
    """Boundary conditions and edge cases for semantic tagging."""

    def test_empty_body_text(
        self,
        semantic_tagger: SemanticTagger,
    ) -> None:
        """Processing with empty body_text should handle gracefully."""
        ctx = PipelineContext()
        ctx.set("body_text", "")
        ctx.set("title", "")

        result_ctx = semantic_tagger.process(ctx)
        tags = result_ctx.get("tags")
        assert tags is not None
        assert isinstance(tags, list)

    def test_missing_body_text_raises(
        self,
        semantic_tagger: SemanticTagger,
    ) -> None:
        """When body_text key is missing, should raise ValueError or KeyError."""
        ctx = PipelineContext()
        with pytest.raises((ValueError, KeyError)):
            semantic_tagger.process(ctx)

    def test_missing_title_still_works(
        self,
        semantic_tagger: SemanticTagger,
    ) -> None:
        """When title is missing but body_text exists, should still produce tags."""
        ctx = PipelineContext()
        ctx.set("body_text", SAMPLE_BODY_TEXT)
        # No title set
        result_ctx = semantic_tagger.process(ctx)
        tags = result_ctx.get("tags")
        assert tags is not None
        assert isinstance(tags, list)
