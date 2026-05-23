"""PROCESSOR_REGISTRY: central mapping of processor class names to classes."""

from __future__ import annotations

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.processors.dedup import ContentDedup
from intellisource.pipeline.processors.parser import HTMLParser
from intellisource.pipeline.processors.tagger import KeywordTagger

PROCESSOR_REGISTRY: dict[str, type[BaseProcessor]] = {
    "HTMLParser": HTMLParser,
    "ContentDedup": ContentDedup,
    "KeywordTagger": KeywordTagger,
}


def get_processor(name: str) -> type[BaseProcessor]:
    """Return the processor class for *name*, raising ValueError if unknown."""
    if name not in PROCESSOR_REGISTRY:
        raise ValueError(f"Unknown processor: {name}")
    return PROCESSOR_REGISTRY[name]
