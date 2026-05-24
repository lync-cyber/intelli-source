"""Adaptive scheduling and retry policy for the collector module.

Implements:
- AC-009: Dynamic interval calculation based on historical update frequency
- AC-012: Auto-retry with exponential backoff (3 attempts)
- AC-T015-1: New sources use default interval; adaptive after 5 collections
- AC-T015-2: Adaptive interval clamped to [120s, 86400s]
- AC-T015-3: Consecutive errors extend interval; success restores it
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

MIN_INTERVAL: int = 120  # 2 minutes (arch §2.M-002 default)
MAX_INTERVAL: int = 86400  # 24 hours
ADAPTIVE_THRESHOLD: int = 5  # minimum collections before adaptive kicks in


@runtime_checkable
class HasSourceStats(Protocol):
    """Protocol for objects carrying source statistics."""

    collect_count: int
    avg_update_interval: float
    error_count: int
    current_interval: int
    default_interval: int


class AdaptiveScheduler:
    """Calculate next collection interval based on source update patterns."""

    def calculate_next_interval(self, source_stats: HasSourceStats) -> int:
        """Return the next collection interval in seconds.

        For new sources (collect_count < 5), returns default_interval.
        For mature sources, adapts based on avg_update_interval with
        error backoff and clamping to [120, 86400].
        """
        if source_stats.collect_count < ADAPTIVE_THRESHOLD:
            return source_stats.default_interval

        # Base interval tracks the average update interval
        interval = source_stats.avg_update_interval

        # Apply error backoff: multiply by (1 + error_count)
        if source_stats.error_count > 0:
            interval = interval * (1 + source_stats.error_count)

        # Clamp to allowed range
        clamped = int(max(MIN_INTERVAL, min(MAX_INTERVAL, interval)))
        return clamped

    def record_success(self, source_id: str) -> None:
        """Record a successful fetch; reserved for future stat tracking."""

    def record_failure(self, source_id: str) -> None:
        """Record a failed fetch; reserved for future stat tracking."""


class RetryPolicy:
    """Exponential backoff retry policy with a maximum of 3 retries."""

    max_retries: int = 3

    def should_retry(self, attempt: int, error: Exception) -> bool:
        """Return True if the given attempt number is within retry limit."""
        return attempt <= self.max_retries

    def get_delay(self, attempt: int) -> float:
        """Return delay for the given attempt (exponential: 2^(n-1))."""
        return float(2 ** (attempt - 1))
