"""PipelineEngine: executes processors with middleware and streaming support."""

import time
from collections.abc import AsyncIterator
from typing import Sequence

from intellisource.observability.logging import get_logger
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext
from intellisource.pipeline.middleware import BaseMiddleware, MiddlewareChain

logger = get_logger(__name__)


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
        errors: list[dict[str, str]] = []
        for processor in self._processors:
            try:
                context = processor.process(context)
            except Exception as exc:
                if self._fail_fast:
                    raise
                errors.append(
                    {"processor": type(processor).__name__, "error": str(exc)}
                )
        if errors:
            context.set("errors", errors)
        return context

    def execute(self, context: PipelineContext) -> PipelineContext:
        """Execute all processors through the middleware chain."""
        logger.debug("Pipeline start: %d processors", len(self._processors))
        start = time.monotonic()

        chain = MiddlewareChain(
            middlewares=self._middlewares,
            handler=self._run_processors,
        )
        context = chain.execute(context)

        elapsed = time.monotonic() - start
        context.set("elapsed_time", elapsed)
        logger.debug("Pipeline complete: elapsed=%.4fs", elapsed)
        return context

    async def execute_stream(
        self, ctx: PipelineContext
    ) -> AsyncIterator[PipelineContext]:
        """Yield context after each processor completes.

        Mirrors fail_fast semantics from execute(): when fail_fast=False,
        processor exceptions are caught and appended to ctx["errors"] before
        yielding; when fail_fast=True, the exception propagates immediately.
        """
        for processor in self._processors:
            try:
                ctx = processor.process(ctx)
            except Exception as exc:
                if self._fail_fast:
                    raise
                errors: list[dict[str, str]] = list(ctx.get("errors") or [])
                errors.append(
                    {"processor": type(processor).__name__, "error": str(exc)}
                )
                ctx.set("errors", errors)
            yield ctx
