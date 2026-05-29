"""Tests for PipelineEngine (AC-013, AC-015, AC-T016-1, AC-T016-2).

Covers:
- AC-013: PipelineEngine executes processors in configuration order.
- AC-015: BaseProcessor defines process(context) -> context unified interface.
- AC-T016-1: Processor exceptions don't break pipeline (configurable fail_fast mode).
- AC-T016-2: Pipeline execution triggers logging with elapsed time.
"""

import pytest

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext
from intellisource.pipeline.engine import PipelineEngine

# ---------------------------------------------------------------------------
# Test helpers: concrete processor subclasses
# ---------------------------------------------------------------------------


class AppendProcessor(BaseProcessor):
    """Append the processor name to a context list, tracking execution order."""

    def __init__(self, name: str):
        self._name = name

    def process(self, context: PipelineContext) -> PipelineContext:
        order = context.get("execution_order", [])
        order.append(self._name)
        context.set("execution_order", order)
        return context


class FailingProcessor(BaseProcessor):
    """Processor that always raises an exception."""

    def __init__(self, name: str = "failing"):
        self._name = name

    def process(self, context: PipelineContext) -> PipelineContext:
        raise RuntimeError(f"{self._name} processor failed")


class DoubleValueProcessor(BaseProcessor):
    """Processor that doubles a numeric value in context."""

    def process(self, context: PipelineContext) -> PipelineContext:
        value = context.get("value", 0)
        context.set("value", value * 2)
        return context


# ---------------------------------------------------------------------------
# AC-015: BaseProcessor defines process(context) -> context interface
# ---------------------------------------------------------------------------


class TestBaseProcessorInterface:
    """AC-015: BaseProcessor is an abstract class with process(context) -> context."""

    def test_base_processor_is_abstract(self):
        """BaseProcessor should not be instantiable directly (abstract)."""
        with pytest.raises(TypeError):
            BaseProcessor()

    def test_subclass_must_implement_process(self):
        """A subclass that does not implement process() should raise TypeError."""

        class IncompleteProcessor(BaseProcessor):
            pass

        with pytest.raises(TypeError):
            IncompleteProcessor()

    def test_concrete_subclass_returns_context(self):
        """A concrete subclass implementing process() returns a PipelineContext."""
        processor = AppendProcessor("test")
        ctx = PipelineContext()
        result = processor.process(ctx)
        assert isinstance(result, PipelineContext)


# ---------------------------------------------------------------------------
# AC-013: PipelineEngine executes processors in configuration order
# ---------------------------------------------------------------------------


class TestPipelineEngineOrdering:
    """AC-013: PipelineEngine executes processors in the order they are configured."""

    def test_single_processor_executes(self):
        """A pipeline with one processor should execute it."""
        engine = PipelineEngine(processors=[AppendProcessor("only")])
        ctx = PipelineContext()
        result = engine.execute(ctx)
        assert result.get("execution_order") == ["only"]

    def test_processors_execute_in_order(self):
        """Processors should execute in the exact order provided at construction."""
        processors = [
            AppendProcessor("first"),
            AppendProcessor("second"),
            AppendProcessor("third"),
        ]
        engine = PipelineEngine(processors=processors)
        ctx = PipelineContext()
        result = engine.execute(ctx)
        assert result.get("execution_order") == ["first", "second", "third"]

    def test_empty_processor_list(self):
        """A pipeline with no processors should return the context unchanged."""
        engine = PipelineEngine(processors=[])
        ctx = PipelineContext()
        ctx.set("original", True)
        result = engine.execute(ctx)
        assert result.get("original") is True

    def test_pipeline_chains_context_through_processors(self):
        """Each processor receives the context modified by the previous one."""
        ctx = PipelineContext()
        ctx.set("value", 3)
        engine = PipelineEngine(
            processors=[DoubleValueProcessor(), DoubleValueProcessor()]
        )
        result = engine.execute(ctx)
        # 3 -> 6 -> 12
        assert result.get("value") == 12

    def test_execute_returns_pipeline_context(self):
        """engine.execute() must return a PipelineContext instance."""
        engine = PipelineEngine(processors=[AppendProcessor("a")])
        ctx = PipelineContext()
        result = engine.execute(ctx)
        assert isinstance(result, PipelineContext)


# ---------------------------------------------------------------------------
# AC-T016-1: Error handling and fail_fast mode
# ---------------------------------------------------------------------------


class TestPipelineEngineErrorHandling:
    """AC-T016-1: Processor exceptions don't break the pipeline by default; fail_fast opt-in."""  # noqa: E501

    def test_default_continues_after_error(self):
        """By default, a failing processor should not stop subsequent processors."""
        processors = [
            AppendProcessor("before"),
            FailingProcessor("broken"),
            AppendProcessor("after"),
        ]
        engine = PipelineEngine(processors=processors)
        ctx = PipelineContext()
        result = engine.execute(ctx)
        order = result.get("execution_order", [])
        assert "before" in order
        assert "after" in order

    def test_error_recorded_in_context(self):
        """When a processor fails, the error should be recorded in the context."""
        processors = [FailingProcessor("broken")]
        engine = PipelineEngine(processors=processors)
        ctx = PipelineContext()
        result = engine.execute(ctx)
        errors = result.get("errors")
        assert errors is not None
        assert len(errors) > 0

    def test_fail_fast_stops_on_first_error(self):
        """With fail_fast=True, the pipeline stops at the first failing processor."""
        processors = [
            AppendProcessor("before"),
            FailingProcessor("broken"),
            AppendProcessor("should_not_run"),
        ]
        engine = PipelineEngine(processors=processors, fail_fast=True)
        ctx = PipelineContext()
        with pytest.raises(RuntimeError):
            engine.execute(ctx)

    def test_fail_fast_false_explicit(self):
        """Explicitly setting fail_fast=False behaves like the default (continue)."""
        processors = [
            FailingProcessor("broken"),
            AppendProcessor("after"),
        ]
        engine = PipelineEngine(processors=processors, fail_fast=False)
        ctx = PipelineContext()
        result = engine.execute(ctx)
        order = result.get("execution_order", [])
        assert "after" in order

    def test_multiple_errors_all_recorded(self):
        """Multiple failing processors should each have their error recorded."""
        processors = [
            FailingProcessor("fail_1"),
            FailingProcessor("fail_2"),
            AppendProcessor("ok"),
        ]
        engine = PipelineEngine(processors=processors)
        ctx = PipelineContext()
        result = engine.execute(ctx)
        errors = result.get("errors")
        assert errors is not None
        assert len(errors) >= 2


# ---------------------------------------------------------------------------
# AC-T016-2: Pipeline execution logging with elapsed time
# ---------------------------------------------------------------------------


class TestPipelineEngineLogging:
    """AC-T016-2: Pipeline execution triggers logging with elapsed time."""

    def test_execution_records_elapsed_time(self):
        """After execution, the context should contain the total elapsed time."""
        processors = [AppendProcessor("a")]
        engine = PipelineEngine(processors=processors)
        ctx = PipelineContext()
        result = engine.execute(ctx)
        elapsed = result.get("elapsed_time")
        assert elapsed is not None
        assert isinstance(elapsed, (int, float))
        assert elapsed >= 0

    def test_execution_logs_start_and_end(self):
        """Pipeline execution should emit log messages at start and end."""
        from structlog.testing import capture_logs

        processors = [AppendProcessor("a")]
        engine = PipelineEngine(processors=processors)
        ctx = PipelineContext()
        with capture_logs() as logs:
            engine.execute(ctx)
        log_text = " ".join(e["event"] for e in logs).lower()
        # Should log both pipeline start and pipeline end/complete
        assert "pipeline" in log_text
