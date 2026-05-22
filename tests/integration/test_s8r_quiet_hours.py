"""AC-4: quiet_hours timezone — FrequencyController._in_quiet_range() and
is_quiet_hours() respect Asia/Shanghai timezone.

Verifies:
- UTC 14:00 (Beijing 22:00) is inside quiet_hours 22:00-08:00  → True
- UTC 00:00 (Beijing 08:00) is NOT inside quiet_hours 22:00-08:00 → False
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from intellisource.distributor.frequency import FrequencyController

_in_quiet_range = FrequencyController._in_quiet_range


class _FixedClock:
    """A clock that always returns a fixed UTC datetime."""

    def __init__(self, utc_dt: datetime) -> None:
        self._dt = utc_dt

    def now(self) -> datetime:
        return self._dt


def _make_subscription(
    *,
    timezone_name: str = "Asia/Shanghai",
    quiet_start: str = "22:00",
    quiet_end: str = "08:00",
    frequency: str = "realtime",
    last_sent_at: Any = None,
) -> MagicMock:
    """Return a mock subscription with the given quiet hours and timezone."""
    sub = MagicMock()
    sub.timezone = timezone_name
    sub.quiet_hours = {"start": quiet_start, "end": quiet_end}
    sub.frequency = frequency
    sub.last_sent_at = last_sent_at
    return sub


class TestQuietHoursTimezone:
    """AC-4: quiet hours enforce cross-midnight range in Asia/Shanghai."""

    def test_in_quiet_range_cross_midnight_inside(self) -> None:
        """_in_quiet_range(22*60, 22*60, 8*60) is True (boundary: at start)."""
        # 22:00 is the very first minute of the quiet window 22:00-08:00
        result = _in_quiet_range(
            current_minutes=22 * 60,
            start_minutes=22 * 60,
            end_minutes=8 * 60,
        )
        assert result is True, "22:00 (current) must be inside quiet window 22:00-08:00"

    def test_in_quiet_range_cross_midnight_outside(self) -> None:
        """_in_quiet_range(8*60, 22*60, 8*60) is False (boundary: at end)."""
        # 08:00 is the boundary that ends the window (exclusive upper bound)
        result = _in_quiet_range(
            current_minutes=8 * 60,
            start_minutes=22 * 60,
            end_minutes=8 * 60,
        )
        assert result is False, (
            "08:00 must NOT be inside quiet 22:00-08:00 (end exclusive)"
        )

    def test_is_quiet_hours_utc_14_maps_to_beijing_22_returns_true(self) -> None:
        """UTC 14:00 → Beijing 22:00 → inside quiet window 22:00-08:00 → True."""
        utc_14 = datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        controller = FrequencyController(clock=_FixedClock(utc_14))
        sub = _make_subscription(
            timezone_name="Asia/Shanghai",
            quiet_start="22:00",
            quiet_end="08:00",
        )

        result = controller.is_quiet_hours(sub)

        assert result is True, (
            "UTC 14:00 = Beijing 22:00 must be inside quiet window 22:00-08:00"
        )

    def test_is_quiet_hours_utc_00_maps_to_beijing_08_returns_false(self) -> None:
        """UTC 00:00 → Beijing 08:00 → NOT inside quiet window 22:00-08:00 → False."""
        utc_00 = datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        controller = FrequencyController(clock=_FixedClock(utc_00))
        sub = _make_subscription(
            timezone_name="Asia/Shanghai",
            quiet_start="22:00",
            quiet_end="08:00",
        )

        result = controller.is_quiet_hours(sub)

        assert result is False, (
            "UTC 00:00 = Beijing 08:00 must NOT be inside 22:00-08:00"
        )

    def test_is_quiet_hours_midday_beijing_outside_quiet_window(self) -> None:
        """UTC 04:00 → Beijing 12:00 → not in quiet window 22:00-08:00 → False."""
        utc_04 = datetime(2024, 1, 15, 4, 0, 0, tzinfo=timezone.utc)
        controller = FrequencyController(clock=_FixedClock(utc_04))
        sub = _make_subscription(
            timezone_name="Asia/Shanghai",
            quiet_start="22:00",
            quiet_end="08:00",
        )

        result = controller.is_quiet_hours(sub)

        assert result is False, (
            "UTC 04:00 = Beijing 12:00 must NOT be inside quiet window 22:00-08:00"
        )

    def test_is_quiet_hours_midnight_beijing_inside_quiet_window(self) -> None:
        """UTC 16:00 → Beijing 00:00 → inside quiet window 22:00-08:00 → True."""
        utc_16 = datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc)
        controller = FrequencyController(clock=_FixedClock(utc_16))
        sub = _make_subscription(
            timezone_name="Asia/Shanghai",
            quiet_start="22:00",
            quiet_end="08:00",
        )

        result = controller.is_quiet_hours(sub)

        assert result is True, (
            "UTC 16:00 = Beijing 00:00 must be inside quiet window 22:00-08:00 "
            "(cross-midnight range)"
        )
