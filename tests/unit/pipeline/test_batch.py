"""Tests for BatchProcessor (AC-017, AC-T017-2).

Covers:
- AC-017: Support batch mode — pass multiple items; processor handles them in bulk.
- AC-T017-2: In batch mode, pipeline context maintains independent state per item.
"""

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.batch import BatchProcessor
from intellisource.pipeline.context import PipelineContext

# ---------------------------------------------------------------------------
# Helper: concrete processor stubs for testing batch processing
# ---------------------------------------------------------------------------


class _UpperCaseProcessor(BaseProcessor):
    """Stub processor that uppercases the 'text' field in context."""

    def process(self, context: PipelineContext) -> PipelineContext:
        text = context.get("text", "")
        context.set("text", text.upper())
        return context


class _CounterProcessor(BaseProcessor):
    """Stub processor that increments a 'counter' field in context."""

    def process(self, context: PipelineContext) -> PipelineContext:
        current = context.get("counter", 0)
        context.set("counter", current + 1)
        return context


class _FailingProcessor(BaseProcessor):
    """Stub processor that raises an exception when content_type is 'bad'."""

    def process(self, context: PipelineContext) -> PipelineContext:
        if context.get("content_type") == "bad":
            raise ValueError("Simulated processing failure")
        context.set("processed", True)
        return context


# ===========================================================================
# BatchProcessor - basic batch processing
# ===========================================================================


class TestBatchProcessorBasic:
    """AC-017: BatchProcessor wraps a BaseProcessor and processes multiple items."""

    def test_process_batch_returns_list(self):
        """process_batch should return a list of PipelineContext objects."""
        proc = _UpperCaseProcessor()
        batch = BatchProcessor(proc)

        ctx1 = PipelineContext()
        ctx1.set("text", "hello")
        ctx2 = PipelineContext()
        ctx2.set("text", "world")

        results = batch.process_batch([ctx1, ctx2])

        assert isinstance(results, list)
        assert len(results) == 2

    def test_process_batch_applies_processor_to_each_item(self):
        """Each item in the batch should be processed by the wrapped processor."""
        proc = _UpperCaseProcessor()
        batch = BatchProcessor(proc)

        ctx1 = PipelineContext()
        ctx1.set("text", "hello")
        ctx2 = PipelineContext()
        ctx2.set("text", "world")

        results = batch.process_batch([ctx1, ctx2])

        assert results[0].get("text") == "HELLO"
        assert results[1].get("text") == "WORLD"

    def test_process_batch_empty_list(self):
        """process_batch with an empty list should return an empty list."""
        proc = _UpperCaseProcessor()
        batch = BatchProcessor(proc)

        results = batch.process_batch([])
        assert results == []

    def test_process_batch_single_item(self):
        """process_batch with a single item should process it correctly."""
        proc = _UpperCaseProcessor()
        batch = BatchProcessor(proc)

        ctx = PipelineContext()
        ctx.set("text", "single")

        results = batch.process_batch([ctx])
        assert len(results) == 1
        assert results[0].get("text") == "SINGLE"


# ===========================================================================
# BatchProcessor - independent state per item (AC-T017-2)
# ===========================================================================


class TestBatchProcessorIndependentState:
    """AC-T017-2: Each context maintains independent state during batch processing."""

    def test_items_do_not_share_state(self):
        """Processing one item should not affect the state of another item."""
        proc = _CounterProcessor()
        batch = BatchProcessor(proc)

        ctx1 = PipelineContext()
        ctx1.set("counter", 10)
        ctx2 = PipelineContext()
        ctx2.set("counter", 20)

        results = batch.process_batch([ctx1, ctx2])

        # Each counter should be incremented independently
        assert results[0].get("counter") == 11
        assert results[1].get("counter") == 21

    def test_each_item_has_own_data(self):
        """Items with different fields should remain independent after processing."""
        proc = _UpperCaseProcessor()
        batch = BatchProcessor(proc)

        ctx1 = PipelineContext()
        ctx1.set("text", "alpha")
        ctx1.set("source_type", "rss")

        ctx2 = PipelineContext()
        ctx2.set("text", "beta")
        ctx2.set("source_type", "api")

        results = batch.process_batch([ctx1, ctx2])

        # Text processed independently
        assert results[0].get("text") == "ALPHA"
        assert results[1].get("text") == "BETA"
        # Other fields preserved independently
        assert results[0].get("source_type") == "rss"
        assert results[1].get("source_type") == "api"


# ===========================================================================
# BatchProcessor - failure isolation
# ===========================================================================


class TestBatchProcessorFailureIsolation:
    """AC-017 / AC-T017-2: One item failing must not block other items from running."""

    def test_failure_in_one_item_does_not_block_others(self):
        """When one item fails, other items should still be processed successfully."""
        proc = _FailingProcessor()
        batch = BatchProcessor(proc)

        ctx1 = PipelineContext()
        ctx1.set("content_type", "good")

        ctx2 = PipelineContext()
        ctx2.set("content_type", "bad")  # This one will fail

        ctx3 = PipelineContext()
        ctx3.set("content_type", "good")

        results = batch.process_batch([ctx1, ctx2, ctx3])

        assert len(results) == 3
        # Items 0 and 2 should be processed successfully
        assert results[0].get("processed") is True
        assert results[2].get("processed") is True

    def test_failed_item_preserves_original_context(self):
        """A failed item retains its original context (not mutated by the failure)."""
        proc = _FailingProcessor()
        batch = BatchProcessor(proc)

        ctx1 = PipelineContext()
        ctx1.set("content_type", "bad")
        ctx1.set("original_data", "keep_me")

        results = batch.process_batch([ctx1])

        assert len(results) == 1
        # The original data should still be accessible
        assert results[0].get("original_data") == "keep_me"
        # The 'processed' flag should NOT be set since the processor failed
        assert results[0].get("processed") is not True

    def test_all_items_fail_returns_all_contexts(self):
        """Even if all items fail, process_batch should return a result for each."""
        proc = _FailingProcessor()
        batch = BatchProcessor(proc)

        items = []
        for i in range(3):
            ctx = PipelineContext()
            ctx.set("content_type", "bad")
            ctx.set("index", i)
            items.append(ctx)

        results = batch.process_batch(items)

        assert len(results) == 3
        for i, result in enumerate(results):
            assert result.get("index") == i
