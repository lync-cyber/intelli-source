"""Tests for PushOptimizer content optimization processor.

Covers:
- PushOptimizer conforms to BaseProcessor interface
- LLM-based optimization normal path
- Truncation fallback when LLM fails
- Uses load_prompt (template-based prompt, not hardcoded)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.llm.processors.optimizer import PushOptimizer
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_TITLE = "Breaking: New AI Model Achieves Record Performance"
SAMPLE_BODY = (
    "A research team announced today that their latest model surpasses "
    "all existing benchmarks. The model uses a novel architecture that "
    "combines transformers with state-space models for improved efficiency."
)

SAMPLE_LLM_OUTPUT = json.dumps(
    {
        "title": "AI Model Sets New Record",
        "summary": "New AI model surpasses all benchmarks with novel architecture.",
    }
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gateway() -> AsyncMock:
    """Create a mock LLMGateway that returns valid optimization JSON."""
    gateway = AsyncMock()
    result = MagicMock()
    result.content = SAMPLE_LLM_OUTPUT
    result.metadata = {
        "input_tokens": 150,
        "output_tokens": 40,
        "latency_ms": 350.0,
        "model": "gpt-4o-mini",
    }
    gateway.complete = AsyncMock(return_value=result)
    return gateway


@pytest.fixture
def mock_gateway_failing() -> AsyncMock:
    """Create a mock LLMGateway that always raises."""
    gateway = AsyncMock()
    gateway.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    return gateway


@pytest.fixture
def mock_call_log() -> AsyncMock:
    """Create a mock call log."""
    call_log = AsyncMock()
    call_log.record = AsyncMock()
    return call_log


@pytest.fixture
def context() -> PipelineContext:
    """Create a pipeline context with sample content."""
    ctx = PipelineContext()
    ctx.set("title", SAMPLE_TITLE)
    ctx.set("body_text", SAMPLE_BODY)
    ctx.set("push_channel", "wechat")
    return ctx


# ---------------------------------------------------------------------------
# Tests: interface
# ---------------------------------------------------------------------------


class TestPushOptimizerInterface:
    """PushOptimizer conforms to BaseProcessor."""

    def test_is_base_processor(
        self, mock_gateway: AsyncMock, mock_call_log: AsyncMock
    ) -> None:
        optimizer = PushOptimizer(mock_gateway, mock_call_log)
        assert isinstance(optimizer, BaseProcessor)


# ---------------------------------------------------------------------------
# Tests: LLM optimization path
# ---------------------------------------------------------------------------


class TestPushOptimizerLLMPath:
    """LLM-based optimization produces optimized title and summary."""

    def test_sets_optimized_title(
        self,
        mock_gateway: AsyncMock,
        mock_call_log: AsyncMock,
        context: PipelineContext,
    ) -> None:
        optimizer = PushOptimizer(mock_gateway, mock_call_log)
        result = optimizer.process(context)

        assert result.get("optimized_title") == "AI Model Sets New Record"

    def test_sets_optimized_summary(
        self,
        mock_gateway: AsyncMock,
        mock_call_log: AsyncMock,
        context: PipelineContext,
    ) -> None:
        optimizer = PushOptimizer(mock_gateway, mock_call_log)
        result = optimizer.process(context)

        assert "novel architecture" in result.get("optimized_summary")

    def test_records_call_log(
        self,
        mock_gateway: AsyncMock,
        mock_call_log: AsyncMock,
        context: PipelineContext,
    ) -> None:
        optimizer = PushOptimizer(mock_gateway, mock_call_log)
        optimizer.process(context)

        mock_call_log.record.assert_awaited_once()

    def test_uses_load_prompt(
        self,
        mock_gateway: AsyncMock,
        mock_call_log: AsyncMock,
        context: PipelineContext,
    ) -> None:
        """Verify that the processor delegates to load_prompt, not hardcoded strings."""
        with patch(
            "intellisource.llm.processors.optimizer.load_prompt",
            return_value="mocked prompt",
        ) as mock_load:
            optimizer = PushOptimizer(mock_gateway, mock_call_log)
            optimizer.process(context)

            mock_load.assert_called_once_with(
                "optimizer",
                channel="wechat",
                title=SAMPLE_TITLE,
                body_text=SAMPLE_BODY,
            )


# ---------------------------------------------------------------------------
# Tests: fallback path
# ---------------------------------------------------------------------------


class TestPushOptimizerFallback:
    """Fallback to truncation when LLM is unavailable."""

    def test_fallback_sets_truncated_title(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
        context: PipelineContext,
    ) -> None:
        optimizer = PushOptimizer(mock_gateway_failing, mock_call_log)
        result = optimizer.process(context)

        assert result.get("optimized_title") == SAMPLE_TITLE

    def test_fallback_sets_summary(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
        context: PipelineContext,
    ) -> None:
        optimizer = PushOptimizer(mock_gateway_failing, mock_call_log)
        result = optimizer.process(context)

        assert len(result.get("optimized_summary")) > 0

    def test_fallback_with_long_title(
        self,
        mock_gateway_failing: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        ctx = PipelineContext()
        long_title = "A" * 200
        ctx.set("title", long_title)
        ctx.set("body_text", "Short body.")
        ctx.set("push_channel", "email")

        optimizer = PushOptimizer(mock_gateway_failing, mock_call_log)
        result = optimizer.process(ctx)

        assert len(result.get("optimized_title")) <= 80


# ---------------------------------------------------------------------------
# Tests: default channel
# ---------------------------------------------------------------------------


class TestPushOptimizerDefaults:
    """Default push_channel when not provided."""

    def test_default_channel(
        self,
        mock_gateway: AsyncMock,
        mock_call_log: AsyncMock,
    ) -> None:
        ctx = PipelineContext()
        ctx.set("title", SAMPLE_TITLE)
        ctx.set("body_text", SAMPLE_BODY)
        # No push_channel set

        optimizer = PushOptimizer(mock_gateway, mock_call_log)
        result = optimizer.process(ctx)

        assert result.get("optimized_title") is not None
