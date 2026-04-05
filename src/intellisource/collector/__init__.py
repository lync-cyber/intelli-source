"""Collector engine module (M-002): pluggable content collection."""

from intellisource.collector.base import BaseCollector, RawContent, compute_fingerprint
from intellisource.collector.registry import CollectorRegistry

__all__ = [
    "BaseCollector",
    "CollectorRegistry",
    "RawContent",
    "compute_fingerprint",
]
