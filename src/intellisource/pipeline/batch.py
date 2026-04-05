"""BatchProcessor for processing multiple pipeline items in bulk."""

from __future__ import annotations

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext


class BatchProcessor:
    """Wraps a BaseProcessor and applies it to a batch of contexts."""

    def __init__(self, processor: BaseProcessor) -> None:
        self._processor = processor

    def process_batch(self, items: list[PipelineContext]) -> list[PipelineContext]:
        """Process a list of contexts, isolating failures per item.

        Each item is processed independently. If processing an item raises
        an exception, the original context is preserved in the results.
        """
        results: list[PipelineContext] = []
        for item in items:
            try:
                result = self._processor.process(item)
                results.append(result)
            except Exception:
                results.append(item)
        return results
