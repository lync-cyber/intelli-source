"""Processing pipeline module (M-003): composable content processing."""

from intellisource.core.processor import BaseProcessor, PipelineContext
from intellisource.pipeline.engine import PipelineEngine
from intellisource.pipeline.middleware import BaseMiddleware, MiddlewareChain

__all__ = [
    "BaseMiddleware",
    "BaseProcessor",
    "MiddlewareChain",
    "PipelineContext",
    "PipelineEngine",
]
