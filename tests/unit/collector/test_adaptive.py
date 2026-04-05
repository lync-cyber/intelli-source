"""Tests for adaptive scheduling and retry policy in the collector module.

Covers:
- AC-009: Dynamic interval calculation based on historical update frequency
- AC-012: Auto-retry with exponential backoff (3 attempts), failure logging
- AC-T015-1: New sources use default interval; adaptive adjustment after 5 collections
- AC-T015-2: Adaptive interval clamped to [5 min, 24 hours]
- AC-T015-3: Consecutive errors extend interval (backoff); success restores it
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from intellisource.collector.adaptive import AdaptiveScheduler, RetryPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class SourceStats:
    """Minimal stats structure for testing."""

    collect_count: int
    avg_update_interval: float  # seconds
    error_count: int
    current_interval: int  # seconds
    default_interval: int  # seconds


# ---------------------------------------------------------------------------
# AdaptiveScheduler — AC-T015-1: default interval for new sources
# ---------------------------------------------------------------------------


class TestAdaptiveSchedulerNewSource:
    """New sources (collect_count < 5) should always return default_interval."""

    def test_zero_collections_returns_default(self):
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=0,
            avg_update_interval=600,
            error_count=0,
            current_interval=3600,
            default_interval=3600,
        )
        result = scheduler.calculate_next_interval(stats)
        assert result == 3600

    def test_four_collections_still_returns_default(self):
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=4,
            avg_update_interval=300,
            error_count=0,
            current_interval=1800,
            default_interval=1800,
        )
        result = scheduler.calculate_next_interval(stats)
        assert result == 1800

    def test_first_collection_returns_default(self):
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=1,
            avg_update_interval=7200,
            error_count=0,
            current_interval=600,
            default_interval=600,
        )
        result = scheduler.calculate_next_interval(stats)
        assert result == 600


# ---------------------------------------------------------------------------
# AdaptiveScheduler — AC-009 / AC-T015-1: adaptive adjustment after 5 collects
# ---------------------------------------------------------------------------


class TestAdaptiveSchedulerAdaptive:
    """After 5+ collections, interval adapts to avg_update_interval."""

    def test_frequent_updates_shorten_interval(self):
        """Sources updating every 10 min should get a shorter interval than default 1h."""
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=10,
            avg_update_interval=600,  # 10 min average between updates
            error_count=0,
            current_interval=3600,
            default_interval=3600,
        )
        result = scheduler.calculate_next_interval(stats)
        assert result < 3600, "Frequent updates should shorten the interval"

    def test_infrequent_updates_extend_interval(self):
        """Sources updating every 12 hours should get a longer interval than 1h default."""
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=10,
            avg_update_interval=43200,  # 12 hours
            error_count=0,
            current_interval=3600,
            default_interval=3600,
        )
        result = scheduler.calculate_next_interval(stats)
        assert result > 3600, "Infrequent updates should extend the interval"

    def test_exactly_five_collections_triggers_adaptive(self):
        """collect_count == 5 is the boundary; should use adaptive logic."""
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=5,
            avg_update_interval=600,
            error_count=0,
            current_interval=3600,
            default_interval=3600,
        )
        result = scheduler.calculate_next_interval(stats)
        # With frequent updates (600s avg), adaptive should differ from default
        assert result < 3600


# ---------------------------------------------------------------------------
# AdaptiveScheduler — AC-T015-2: interval clamping (min 300s, max 86400s)
# ---------------------------------------------------------------------------


class TestAdaptiveSchedulerClamping:
    """Adaptive interval must be clamped: min=300s (5 min), max=86400s (24h)."""

    def test_very_frequent_updates_clamped_to_minimum(self):
        """Even with extremely frequent updates, interval should not go below 300s."""
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=100,
            avg_update_interval=10,  # updates every 10 seconds
            error_count=0,
            current_interval=300,
            default_interval=3600,
        )
        result = scheduler.calculate_next_interval(stats)
        assert result >= 300, "Interval must not go below 300 seconds (5 minutes)"

    def test_very_infrequent_updates_clamped_to_maximum(self):
        """Even with very rare updates, interval should not exceed 86400s."""
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=100,
            avg_update_interval=604800,  # 7 days between updates
            error_count=0,
            current_interval=86400,
            default_interval=3600,
        )
        result = scheduler.calculate_next_interval(stats)
        assert result <= 86400, "Interval must not exceed 86400 seconds (24 hours)"

    def test_minimum_boundary_exact(self):
        """Interval of exactly 300 is valid (not below minimum)."""
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=50,
            avg_update_interval=60,
            error_count=0,
            current_interval=300,
            default_interval=3600,
        )
        result = scheduler.calculate_next_interval(stats)
        assert result >= 300

    def test_maximum_boundary_exact(self):
        """Interval of exactly 86400 is valid (not above maximum)."""
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=50,
            avg_update_interval=200000,
            error_count=0,
            current_interval=86400,
            default_interval=3600,
        )
        result = scheduler.calculate_next_interval(stats)
        assert result <= 86400


# ---------------------------------------------------------------------------
# AdaptiveScheduler — AC-T015-3: error backoff and recovery
# ---------------------------------------------------------------------------


class TestAdaptiveSchedulerErrorBackoff:
    """Consecutive errors should extend interval; success (error_count=0) restores."""

    def test_errors_extend_interval(self):
        """With errors, interval should be longer than without errors."""
        scheduler = AdaptiveScheduler()
        stats_no_error = SourceStats(
            collect_count=10,
            avg_update_interval=600,
            error_count=0,
            current_interval=3600,
            default_interval=3600,
        )
        stats_with_errors = SourceStats(
            collect_count=10,
            avg_update_interval=600,
            error_count=3,
            current_interval=3600,
            default_interval=3600,
        )
        normal_interval = scheduler.calculate_next_interval(stats_no_error)
        error_interval = scheduler.calculate_next_interval(stats_with_errors)
        assert error_interval > normal_interval, (
            "Errors should cause a longer interval than normal"
        )

    def test_more_errors_extend_further(self):
        """Higher error_count should produce a longer interval."""
        scheduler = AdaptiveScheduler()
        stats_few_errors = SourceStats(
            collect_count=10,
            avg_update_interval=600,
            error_count=1,
            current_interval=3600,
            default_interval=3600,
        )
        stats_many_errors = SourceStats(
            collect_count=10,
            avg_update_interval=600,
            error_count=5,
            current_interval=3600,
            default_interval=3600,
        )
        few_interval = scheduler.calculate_next_interval(stats_few_errors)
        many_interval = scheduler.calculate_next_interval(stats_many_errors)
        assert many_interval > few_interval, (
            "More errors should produce a longer interval"
        )

    def test_error_recovery_restores_normal_interval(self):
        """When error_count returns to 0, interval should match normal calculation."""
        scheduler = AdaptiveScheduler()
        stats_recovered = SourceStats(
            collect_count=10,
            avg_update_interval=600,
            error_count=0,
            current_interval=7200,  # was extended due to errors
            default_interval=3600,
        )
        stats_baseline = SourceStats(
            collect_count=10,
            avg_update_interval=600,
            error_count=0,
            current_interval=3600,
            default_interval=3600,
        )
        recovered = scheduler.calculate_next_interval(stats_recovered)
        baseline = scheduler.calculate_next_interval(stats_baseline)
        # After recovery, interval should be based on update frequency, not on
        # inflated current_interval. Both should produce the same result.
        assert recovered == baseline, (
            "After error recovery (error_count=0), interval should match baseline"
        )

    def test_error_backoff_still_clamped_to_max(self):
        """Error backoff must not push interval above the 86400s ceiling."""
        scheduler = AdaptiveScheduler()
        stats = SourceStats(
            collect_count=10,
            avg_update_interval=43200,
            error_count=10,
            current_interval=86400,
            default_interval=3600,
        )
        result = scheduler.calculate_next_interval(stats)
        assert result <= 86400, "Even with many errors, interval must not exceed 86400s"


# ---------------------------------------------------------------------------
# RetryPolicy — AC-012: 3 retries with exponential backoff
# ---------------------------------------------------------------------------


class TestRetryPolicyMaxRetries:
    """RetryPolicy should allow up to 3 retry attempts."""

    def test_max_retries_attribute(self):
        policy = RetryPolicy()
        assert policy.max_retries == 3

    def test_should_retry_first_attempt(self):
        policy = RetryPolicy()
        assert policy.should_retry(1, RuntimeError("fail")) is True

    def test_should_retry_second_attempt(self):
        policy = RetryPolicy()
        assert policy.should_retry(2, RuntimeError("fail")) is True

    def test_should_retry_third_attempt(self):
        policy = RetryPolicy()
        assert policy.should_retry(3, RuntimeError("fail")) is True

    def test_should_not_retry_fourth_attempt(self):
        policy = RetryPolicy()
        assert policy.should_retry(4, RuntimeError("fail")) is False

    def test_should_not_retry_beyond_max(self):
        policy = RetryPolicy()
        assert policy.should_retry(10, RuntimeError("fail")) is False


class TestRetryPolicyExponentialBackoff:
    """get_delay should return exponential backoff: 1s, 2s, 4s."""

    def test_first_attempt_delay(self):
        policy = RetryPolicy()
        assert policy.get_delay(1) == pytest.approx(1.0)

    def test_second_attempt_delay(self):
        policy = RetryPolicy()
        assert policy.get_delay(2) == pytest.approx(2.0)

    def test_third_attempt_delay(self):
        policy = RetryPolicy()
        assert policy.get_delay(3) == pytest.approx(4.0)


class TestRetryPolicyEdgeCases:
    """Edge cases for RetryPolicy."""

    def test_should_retry_with_zero_attempt(self):
        """Attempt 0 is before any retry; should not retry or handle gracefully."""
        policy = RetryPolicy()
        # attempt=0 means no failure yet; should_retry should return True
        # (the first retry is attempt 1, but 0 is a valid pre-check)
        result = policy.should_retry(0, RuntimeError("fail"))
        assert isinstance(result, bool)

    def test_get_delay_returns_float(self):
        policy = RetryPolicy()
        delay = policy.get_delay(1)
        assert isinstance(delay, (int, float))
