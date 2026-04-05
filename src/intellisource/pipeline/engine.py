"""PipelineEngine: executes processors in order with error handling and logging."""

import logging
import time
from typing import Sequence

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


class PipelineEngine:
    """Executes a sequence of processors in configuration order."""

    def __init__(
        self,
        processors: Sequence[BaseProcessor],
        fail_fast: bool = False,
    ) -> None:
        self._processors = processors
        self._fail_fast = fail_fast

    def execute(self, context: PipelineContext) -> PipelineContext:
        """Execute all processors in order, returning the final context."""
        logger.debug("Pipeline start: %d processors", len(self._processors))
        start = time.monotonic()

        errors: list[str] = []
        for processor in self._processors:
            try:
                context = processor.process(context)
            except Exception as exc:
                if self._fail_fast:
                    raise
                errors.append(str(exc))

        if errors:
            context.set("errors", errors)

        elapsed = time.monotonic() - start
        context.set("elapsed_time", elapsed)
        logger.debug("Pipeline complete: elapsed=%.4fs", elapsed)
        return context
