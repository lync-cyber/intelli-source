"""Tests for timezone-aware quiet hours enforcement.

Covers AC-1 and AC-2:
- AC-1: Subscription.timezone field (default "Asia/Shanghai")
- AC-2: _in_quiet_range uses zoneinfo.ZoneInfo(subscription.timezone) for
        UTC→local conversion before comparison; cross-midnight logic preserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


@dataclass
class StubSubscription:
    """Minimal stub subscription with timezone field (AC-1)."""

    frequency: str = "realtime"
    quiet_hours: dict = field(default_factory=dict)
    last_sent_at: datetime | None = None
    status: str = "active"
    timezone: str = "Asia/Shanghai"  # AC-1 default


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


# ---------------------------------------------------------------------------
# AC-1: Subscription model has timezone field (tested at runtime via dataclass
#        to verify the expected interface before ORM implementation)
# ---------------------------------------------------------------------------


class TestSubscriptionTimezoneAttribute:
    def test_default_timezone_is_asia_shanghai(self):
        """AC-1: Subscription timezone defaults to 'Asia/Shanghai'."""
        sub = StubSubscription()
        assert sub.timezone == "Asia/Shanghai"

    def test_custom_timezone_stored(self):
        """AC-1: Subscription accepts custom timezone string."""
        sub = StubSubscription(timezone="America/New_York")
        assert sub.timezone == "America/New_York"


# ---------------------------------------------------------------------------
# AC-2: is_quiet_hours converts UTC→subscription.timezone before comparing
# ---------------------------------------------------------------------------


class TestQuietHoursTimezoneConversion:
    def _make_controller(self, fake_utc: datetime):
        """Return a FrequencyController with injected clock."""
        from intellisource.distributor.frequency import FrequencyController

        return FrequencyController(clock=FakeClock(fake_utc))

    def test_utc_midnight_is_beijing_0800_not_in_quiet_hours(self):
        """AC-2: UTC 00:00 → Beijing 08:00; quiet_hours 22:00-08:00 → endpoint
        08:00 is quiet_hours end (exclusive), so UTC 00:00 is NOT quiet.
        """
        # UTC 2026-01-01 00:00 = Asia/Shanghai 2026-01-01 08:00
        utc_midnight = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        sub = StubSubscription(
            quiet_hours={"start": "22:00", "end": "08:00"},
            timezone="Asia/Shanghai",
        )
        ctrl = self._make_controller(utc_midnight)
        # 08:00 is the exclusive end of quiet hours → not quiet
        assert ctrl.is_quiet_hours(sub) is False

    def test_utc_2200_is_beijing_0600_next_day_not_in_daytime_window(self):
        """AC-2: UTC 22:00 → Beijing 06:00 next day; quiet_hours 22:00-08:00
        (Beijing local) → 06:00 is inside quiet window, should be quiet.
        """
        # UTC 2026-01-01 22:00 = Asia/Shanghai 2026-01-02 06:00
        utc_2200 = datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc)
        sub = StubSubscription(
            quiet_hours={"start": "22:00", "end": "08:00"},
            timezone="Asia/Shanghai",
        )
        ctrl = self._make_controller(utc_2200)
        # Beijing 06:00 falls in cross-midnight range 22:00-08:00 → quiet
        assert ctrl.is_quiet_hours(sub) is True

    def test_utc_time_in_beijing_daytime_not_quiet(self):
        """AC-2: UTC 05:00 → Beijing 13:00; quiet_hours 22:00-08:00 → not quiet."""
        utc_0500 = datetime(2026, 1, 1, 5, 0, tzinfo=timezone.utc)
        sub = StubSubscription(
            quiet_hours={"start": "22:00", "end": "08:00"},
            timezone="Asia/Shanghai",
        )
        ctrl = self._make_controller(utc_0500)
        assert ctrl.is_quiet_hours(sub) is False

    def test_cross_midnight_range_preserved_in_beijing(self):
        """AC-2: cross-midnight quiet_hours logic is preserved with timezone."""
        # UTC 14:00 → Beijing 22:00 → start of quiet hours
        utc_1400 = datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
        sub = StubSubscription(
            quiet_hours={"start": "22:00", "end": "08:00"},
            timezone="Asia/Shanghai",
        )
        ctrl = self._make_controller(utc_1400)
        # Beijing 22:00 exactly at start → inside quiet hours
        assert ctrl.is_quiet_hours(sub) is True

    def test_america_new_york_timezone_dst_boundary(self):
        """AC-2 security/DST boundary: America/New_York (has DST).
        UTC 2026-03-08 07:00 → NYC is EST (UTC-5) → 02:00 local.
        quiet_hours 01:00-06:00 → 02:00 is inside → quiet.
        """
        utc_0700 = datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)
        sub = StubSubscription(
            quiet_hours={"start": "01:00", "end": "06:00"},
            timezone="America/New_York",
        )
        ctrl = self._make_controller(utc_0700)
        assert ctrl.is_quiet_hours(sub) is True

    def test_no_quiet_hours_returns_false_regardless_of_timezone(self):
        """AC-2: empty quiet_hours with timezone set → never quiet."""
        utc_midnight = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        sub = StubSubscription(
            quiet_hours={},
            timezone="Asia/Shanghai",
        )
        ctrl = self._make_controller(utc_midnight)
        assert ctrl.is_quiet_hours(sub) is False

    def test_same_day_range_with_timezone(self):
        """AC-2: daytime quiet_hours 09:00-17:00 in Asia/Shanghai.
        UTC 03:00 → Beijing 11:00 → inside 09:00-17:00 → quiet.
        """
        utc_0300 = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
        sub = StubSubscription(
            quiet_hours={"start": "09:00", "end": "17:00"},
            timezone="Asia/Shanghai",
        )
        ctrl = self._make_controller(utc_0300)
        assert ctrl.is_quiet_hours(sub) is True

    def test_invalid_timezone_falls_back_to_utc_without_raising(self):
        """invalid timezone must not raise; fallback to UTC and log WARNING."""
        from structlog.testing import capture_logs

        # UTC 03:00 is outside quiet_hours 09:00-17:00 even in UTC
        utc_0300 = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
        sub = StubSubscription(
            quiet_hours={"start": "09:00", "end": "17:00"},
            timezone="Asia/Shanghia",  # intentional typo — invalid zone
        )
        ctrl = self._make_controller(utc_0300)

        with capture_logs() as logs:
            result = ctrl.is_quiet_hours(sub)

        # Must not raise; UTC 03:00 is outside 09:00-17:00 → not quiet
        assert result is False
        assert any("Invalid timezone" in e["event"] for e in logs), (
            "Expected a WARNING log about invalid timezone"
        )
