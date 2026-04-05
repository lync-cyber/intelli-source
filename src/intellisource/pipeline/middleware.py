"""MiddlewareChain and BaseMiddleware: onion-model middleware support."""

from abc import ABC, abstractmethod
from typing import Callable, Sequence

from intellisource.pipeline.context import PipelineContext


class BaseMiddleware(ABC):
    """Abstract middleware with process(ctx, next_fn) interface."""

    @abstractmethod
    def process(
        self,
        ctx: PipelineContext,
        next_fn: Callable[[PipelineContext], PipelineContext],
    ) -> PipelineContext:
        """Process context, calling next_fn to continue the chain."""
        ...


class MiddlewareChain:
    """Executes middlewares in onion model around a core handler."""

    def __init__(
        self,
        middlewares: Sequence[BaseMiddleware],
        handler: Callable[[PipelineContext], PipelineContext],
    ) -> None:
        self._middlewares = middlewares
        self._handler = handler

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        """Execute the middleware chain with the given context."""
        # Build the onion from inside out
        current: Callable[[PipelineContext], PipelineContext] = self._handler
        for middleware in reversed(self._middlewares):
            current = self._wrap(middleware, current)
        return current(ctx)

    @staticmethod
    def _wrap(
        middleware: BaseMiddleware,
        next_fn: Callable[[PipelineContext], PipelineContext],
    ) -> Callable[[PipelineContext], PipelineContext]:
        """Wrap a middleware around a next function."""

        def wrapped(ctx: PipelineContext) -> PipelineContext:
            return middleware.process(ctx, next_fn)

        return wrapped
