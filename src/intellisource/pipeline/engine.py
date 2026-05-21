"""PipelineEngine: executes processors with middleware and streaming support."""

import logging
import time
from collections.abc import AsyncIterator
from typing import Sequence

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext
from intellisource.pipeline.middleware import BaseMiddleware, MiddlewareChain

logger = logging.getLogger(__name__)


class PipelineEngine:
    """Executes a sequence of processors in configuration order.

    Supports an onion-model middleware chain (before/after hooks) and an
    async streaming variant that yields after each processor.
    """

    def __init__(
        self,
        processors: Sequence[BaseProcessor],
        fail_fast: bool = False,
        middlewares: list[BaseMiddleware] | None = None,
    ) -> None:
        self._processors = processors
        self._fail_fast = fail_fast
        self._middlewares: list[BaseMiddleware] = (
            middlewares if middlewares is not None else []
        )

    def _run_processors(self, context: PipelineContext) -> PipelineContext:
        """Run all processors sequentially, collecting errors when not fail_fast."""
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
        return context

    def execute(self, context: PipelineContext) -> PipelineContext:
        """Execute all processors through the middleware chain."""
        logger.debug("Pipeline start: %d processors", len(self._processors))
        start = time.monotonic()

        if self._middlewares:
            chain = MiddlewareChain(
                middlewares=self._middlewares,
                handler=self._run_processors,
            )
            context = chain.execute(context)
        else:
            context = self._run_processors(context)

        elapsed = time.monotonic() - start
        context.set("elapsed_time", elapsed)
        logger.debug("Pipeline complete: elapsed=%.4fs", elapsed)
        return context

    async def execute_stream(
        self, ctx: PipelineContext
    ) -> AsyncIterator[PipelineContext]:
        """Yield context after each processor completes."""
        for processor in self._processors:
            ctx = processor.process(ctx)
            yield ctx
