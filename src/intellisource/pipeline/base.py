"""BaseProcessor: abstract base class for pipeline processors."""

from abc import ABC, abstractmethod

from intellisource.pipeline.context import PipelineContext


class BaseProcessor(ABC):
    """Abstract processor with a unified process(context) -> context interface."""

    @abstractmethod
    def process(self, context: PipelineContext) -> PipelineContext:
        """Process the context and return it."""
        ...
