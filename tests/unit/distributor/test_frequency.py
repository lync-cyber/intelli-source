"""Tests for FrequencyController: push frequency control and quiet hours.

Covers:
- AC-046: Push frequency control and quiet hours configuration
- AC-T035-1: FrequencyController batches/delays pushes per subscription
              frequency config
- AC-T035-2: hourly/daily/weekly modes aggregate content before sending
- AC-T035-3: Pushes during quiet hours are delayed until quiet hours end
- AC-T035-4: realtime mode sends immediately (no frequency control)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Lightweight stub data models (no SQLAlchemy dependency)
# ---------------------------------------------------------------------------


@dataclass
class StubSubscription:
    """Minimal Subscription for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    frequency: str = "realtime"
    quiet_hours: dict = field(default_factory=dict)
    last_sent_at: datetime | None = None


class FakeClock:
    """Injectable clock for deterministic time control in tests."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now


# ---------------------------------------------------------------------------
# Lazy import helper
# ---------------------------------------------------------------------------


def _import_frequency():
    """Lazy import to confirm ModuleNotFoundError on missing impl."""
    from intellisource.distributor.frequency import (
        FREQUENCY_OPTIONS,
        FrequencyController,
    )

    return FrequencyController, FREQUENCY_OPTIONS


# ===================================================================
# AC-T035-4: realtime mode sends immediately
# ===================================================================


class TestRealtimeMode:
    """Realtime subscriptions should always send immediately."""

    def test_realtime_should_send_now(self):
        controller_cls, _ = _import_frequency()
        clock = FakeClock(datetime(2026, 4, 8, 14, 30, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(frequency="realtime")

        assert ctrl.should_send_now(sub) is True

    def test_realtime_not_affected_by_last_sent(self):
        controller_cls, _ = _import_frequency()
        clock = FakeClock(datetime(2026, 4, 8, 14, 30, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="realtime",
            last_sent_at=datetime(2026, 4, 8, 14, 29, tzinfo=timezone.utc),
        )

        assert ctrl.should_send_now(sub) is True

    def test_realtime_is_not_in_quiet_hours(self):
        """Realtime mode ignores quiet hours per AC-T035-4."""
        controller_cls, _ = _import_frequency()
        clock = FakeClock(datetime(2026, 4, 8, 23, 0, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="realtime",
            quiet_hours={"start": "22:00", "end": "08:00"},
        )

        # realtime sends immediately regardless
        assert ctrl.should_send_now(sub) is True


# ===================================================================
# AC-T035-1: FrequencyController batches/delays per frequency config
# ===================================================================


class TestHourlyFrequency:
    """Hourly subscriptions should send at most once per hour."""

    def test_hourly_should_send_when_never_sent(self):
        controller_cls, _ = _import_frequency()
        clock = FakeClock(datetime(2026, 4, 8, 14, 30, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(frequency="hourly", last_sent_at=None)

        assert ctrl.should_send_now(sub) is True

    def test_hourly_should_not_send_within_hour(self):
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 30, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="hourly",
            last_sent_at=now - timedelta(minutes=30),
        )

        assert ctrl.should_send_now(sub) is False

    def test_hourly_should_send_after_one_hour(self):
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 30, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="hourly",
            last_sent_at=now - timedelta(hours=1, seconds=1),
        )

        assert ctrl.should_send_now(sub) is True


class TestDailyFrequency:
    """Daily subscriptions should send at most once per day."""

    def test_daily_should_not_send_within_day(self):
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="daily",
            last_sent_at=now - timedelta(hours=12),
        )

        assert ctrl.should_send_now(sub) is False

    def test_daily_should_send_after_24h(self):
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="daily",
            last_sent_at=now - timedelta(hours=24, seconds=1),
        )

        assert ctrl.should_send_now(sub) is True


class TestWeeklyFrequency:
    """Weekly subscriptions should send at most once per week."""

    def test_weekly_should_not_send_within_week(self):
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="weekly",
            last_sent_at=now - timedelta(days=3),
        )

        assert ctrl.should_send_now(sub) is False

    def test_weekly_should_send_after_seven_days(self):
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="weekly",
            last_sent_at=now - timedelta(days=7, seconds=1),
        )

        assert ctrl.should_send_now(sub) is True

    def test_weekly_boundary_exactly_seven_days(self):
        """At exactly 7 days, should allow sending."""
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="weekly",
            last_sent_at=now - timedelta(days=7),
        )

        assert ctrl.should_send_now(sub) is True


# ===================================================================
# AC-T035-3: Quiet hours — pushes delayed until quiet hours end
# ===================================================================


class TestQuietHours:
    """Quiet hours should block non-realtime pushes."""

    def test_within_quiet_hours(self):
        controller_cls, _ = _import_frequency()
        # 23:00 is within 22:00-08:00 quiet window
        clock = FakeClock(datetime(2026, 4, 8, 23, 0, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="hourly",
            quiet_hours={"start": "22:00", "end": "08:00"},
        )

        assert ctrl.is_quiet_hours(sub) is True

    def test_outside_quiet_hours(self):
        controller_cls, _ = _import_frequency()
        # 14:00 is outside 22:00-08:00 quiet window
        clock = FakeClock(datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="hourly",
            quiet_hours={"start": "22:00", "end": "08:00"},
        )

        assert ctrl.is_quiet_hours(sub) is False

    def test_quiet_hours_cross_midnight_early_morning(self):
        """03:00 should be within 22:00-08:00 quiet window (crosses midnight)."""
        controller_cls, _ = _import_frequency()
        clock = FakeClock(datetime(2026, 4, 8, 3, 0, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="daily",
            quiet_hours={"start": "22:00", "end": "08:00"},
        )

        assert ctrl.is_quiet_hours(sub) is True

    def test_quiet_hours_at_boundary_start(self):
        """Exactly at start time should be in quiet hours."""
        controller_cls, _ = _import_frequency()
        clock = FakeClock(datetime(2026, 4, 8, 22, 0, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="hourly",
            quiet_hours={"start": "22:00", "end": "08:00"},
        )

        assert ctrl.is_quiet_hours(sub) is True

    def test_quiet_hours_at_boundary_end(self):
        """Exactly at end time should NOT be in quiet hours."""
        controller_cls, _ = _import_frequency()
        clock = FakeClock(datetime(2026, 4, 8, 8, 0, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="hourly",
            quiet_hours={"start": "22:00", "end": "08:00"},
        )

        assert ctrl.is_quiet_hours(sub) is False

    def test_no_quiet_hours_configured(self):
        """Empty quiet_hours means no quiet period."""
        controller_cls, _ = _import_frequency()
        clock = FakeClock(datetime(2026, 4, 8, 23, 0, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(frequency="hourly", quiet_hours={})

        assert ctrl.is_quiet_hours(sub) is False

    def test_quiet_hours_same_day_range(self):
        """Non-crossing midnight range: 09:00-17:00."""
        controller_cls, _ = _import_frequency()
        clock = FakeClock(datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="hourly",
            quiet_hours={"start": "09:00", "end": "17:00"},
        )

        assert ctrl.is_quiet_hours(sub) is True

    def test_should_send_blocked_by_quiet_hours(self):
        """Even if frequency allows sending, quiet hours should block."""
        controller_cls, _ = _import_frequency()
        clock = FakeClock(datetime(2026, 4, 8, 23, 30, tzinfo=timezone.utc))
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="hourly",
            quiet_hours={"start": "22:00", "end": "08:00"},
            last_sent_at=None,  # never sent, frequency would allow
        )

        # Quiet hours override: should NOT send
        assert ctrl.should_send_now(sub) is False


# ===================================================================
# get_next_send_time
# ===================================================================


class TestGetNextSendTime:
    """get_next_send_time should return correct next window."""

    def test_realtime_next_send_is_now(self):
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(frequency="realtime")

        result = ctrl.get_next_send_time(sub)
        assert result == now

    def test_hourly_next_send_time(self):
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 30, tzinfo=timezone.utc)
        last = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(frequency="hourly", last_sent_at=last)

        result = ctrl.get_next_send_time(sub)
        expected = last + timedelta(hours=1)
        assert result == expected

    def test_daily_next_send_time(self):
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        last = datetime(2026, 4, 7, 10, 0, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(frequency="daily", last_sent_at=last)

        result = ctrl.get_next_send_time(sub)
        expected = last + timedelta(days=1)
        assert result == expected

    def test_next_send_time_delayed_by_quiet_hours(self):
        """If next send falls in quiet hours, delay to quiet hours end."""
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 21, 30, tzinfo=timezone.utc)
        last = datetime(2026, 4, 8, 21, 0, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(
            frequency="hourly",
            quiet_hours={"start": "22:00", "end": "08:00"},
            last_sent_at=last,
        )

        result = ctrl.get_next_send_time(sub)
        # Next hourly would be 22:00 which is quiet; should push to 08:00
        quiet_end = datetime(2026, 4, 9, 8, 0, tzinfo=timezone.utc)
        assert result == quiet_end

    def test_next_send_never_sent_returns_now(self):
        controller_cls, _ = _import_frequency()
        now = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        clock = FakeClock(now)
        ctrl = controller_cls(clock=clock)
        sub = StubSubscription(frequency="daily", last_sent_at=None)

        result = ctrl.get_next_send_time(sub)
        assert result == now


# ===================================================================
# AC-T035-2: Aggregation for hourly/daily/weekly
# ===================================================================


class TestAggregatePending:
    """Non-realtime modes should aggregate content."""

    def test_aggregate_multiple_contents(self):
        controller_cls, _ = _import_frequency()
        ctrl = controller_cls()
        sub_id = uuid.uuid4()
        contents = [
            {"id": "c1", "title": "Article 1"},
            {"id": "c2", "title": "Article 2"},
            {"id": "c3", "title": "Article 3"},
        ]

        result = ctrl.aggregate_pending(sub_id, contents)
        assert isinstance(result, list)
        assert len(result) == 3

    def test_aggregate_empty_contents(self):
        controller_cls, _ = _import_frequency()
        ctrl = controller_cls()
        sub_id = uuid.uuid4()

        result = ctrl.aggregate_pending(sub_id, [])
        assert result == []

    def test_aggregate_deduplicates_by_id(self):
        """Duplicate content IDs should be deduplicated."""
        controller_cls, _ = _import_frequency()
        ctrl = controller_cls()
        sub_id = uuid.uuid4()
        contents = [
            {"id": "c1", "title": "Article 1"},
            {"id": "c1", "title": "Article 1 duplicate"},
            {"id": "c2", "title": "Article 2"},
        ]

        result = ctrl.aggregate_pending(sub_id, contents)
        result_ids = [c["id"] for c in result]
        assert len(result_ids) == 2
        assert "c1" in result_ids
        assert "c2" in result_ids


# ===================================================================
# FREQUENCY_OPTIONS constant
# ===================================================================


class TestFrequencyOptions:
    """FREQUENCY_OPTIONS constant should contain expected values."""

    def test_frequency_options_contains_all_modes(self):
        _, frequency_options = _import_frequency()

        assert frequency_options == {
            "realtime",
            "hourly",
            "daily",
            "weekly",
        }
