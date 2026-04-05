"""ContentDedup processor: detects duplicate content via SHA-256 fingerprint."""

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext


class ContentDedup(BaseProcessor):
    """Mark content as duplicate if its fingerprint has been seen before."""

    def __init__(self, seen_fingerprints: set[str] | None = None) -> None:
        self._seen: set[str] = (
            seen_fingerprints if seen_fingerprints is not None else set()
        )

    def process(self, context: PipelineContext) -> PipelineContext:
        fingerprint: str = context.get("fingerprint", "")
        is_duplicate = fingerprint in self._seen
        if not is_duplicate:
            self._seen.add(fingerprint)
        context.set("is_duplicate", is_duplicate)
        return context
