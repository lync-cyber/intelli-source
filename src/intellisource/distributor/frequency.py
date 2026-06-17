"""Frequency controller for push distribution.

Manages push frequency modes (realtime, hourly, daily, weekly),
quiet hours enforcement, and content aggregation for batch delivery.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from intellisource.config.constants import VALID_FREQUENCIES
from intellisource.distributor.clock import Clock, DefaultClock
from intellisource.observability.logging import get_logger

_logger = get_logger(__name__)

#: Canonical valid push frequencies, single-sourced from the config layer so the
#: scheduler domain logic and the subscription reload validator agree.
FREQUENCY_OPTIONS: frozenset[str] = VALID_FREQUENCIES

_FREQUENCY_INTERVALS: dict[str, timedelta] = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' to (hour, minute)."""
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1])


class FrequencyController:
    """Controls push frequency and quiet hours."""

    def __init__(
        self,
        clock: Clock | None = None,
    ) -> None:
        self._clock: Clock = clock or DefaultClock()

    def should_send_now(self, subscription: Any) -> bool:
        """Check if a push should be sent now."""
        if subscription.frequency == "realtime":
            return True

        if self.is_quiet_hours(subscription):
            return False

        if subscription.last_sent_at is None:
            return True

        interval = _FREQUENCY_INTERVALS.get(subscription.frequency)
        if interval is None:
            return True

        elapsed: timedelta = self._clock.now() - subscription.last_sent_at
        return elapsed >= interval

    @staticmethod
    def _has_quiet_hours(qh: dict[str, str]) -> bool:
        """Return True when quiet-hours dict has start and end."""
        return bool(qh and "start" in qh and "end" in qh)

    @staticmethod
    def _in_quiet_range(
        current_minutes: int,
        start_minutes: int,
        end_minutes: int,
    ) -> bool:
        """Check if *current_minutes* falls in [start, end) range.

        Handles both same-day (09:00-17:00) and cross-midnight
        (22:00-08:00) ranges.
        """
        if start_minutes <= end_minutes:
            return start_minutes <= current_minutes < end_minutes
        return current_minutes >= start_minutes or current_minutes < end_minutes

    def is_quiet_hours(self, subscription: Any) -> bool:
        """Check if current time falls within quiet hours.

        Converts UTC clock time to subscription.timezone before comparison.
        """
        qh = subscription.quiet_hours
        if not self._has_quiet_hours(qh):
            return False

        now_utc = self._clock.now()
        tz_name: str = getattr(subscription, "timezone", "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, KeyError):
            _logger.warning(
                "Invalid timezone %r on subscription, falling back to UTC", tz_name
            )
            tz = ZoneInfo("UTC")
        local_now = now_utc.astimezone(tz)
        current_minutes = local_now.hour * 60 + local_now.minute

        start_h, start_m = _parse_time(qh["start"])
        end_h, end_m = _parse_time(qh["end"])

        return self._in_quiet_range(
            current_minutes,
            start_h * 60 + start_m,
            end_h * 60 + end_m,
        )

    def get_next_send_time(self, subscription: Any) -> datetime:
        """Calculate the next send time for a subscription."""
        now = self._clock.now()

        if subscription.frequency == "realtime":
            return now

        if subscription.last_sent_at is None:
            return now

        interval = _FREQUENCY_INTERVALS.get(subscription.frequency)
        if interval is None:
            return now

        next_time: datetime = subscription.last_sent_at + interval

        # If next_time falls in quiet hours, push to quiet-hours end
        qh = subscription.quiet_hours
        if self._has_quiet_hours(qh):
            start_h, start_m = _parse_time(qh["start"])
            end_h, end_m = _parse_time(qh["end"])
            next_minutes = next_time.hour * 60 + next_time.minute

            if self._in_quiet_range(
                next_minutes,
                start_h * 60 + start_m,
                end_h * 60 + end_m,
            ):
                quiet_end = next_time.replace(
                    hour=end_h,
                    minute=end_m,
                    second=0,
                    microsecond=0,
                )
                if quiet_end <= next_time:
                    quiet_end += timedelta(days=1)
                next_time = quiet_end

        return next_time

    def aggregate_pending(
        self,
        subscription_id: UUID,
        contents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Aggregate pending content, deduplicating by id."""
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for item in contents:
            item_id = item.get("id")
            if item_id is not None and item_id in seen:
                continue
            if item_id is not None:
                seen.add(item_id)
            result.append(item)
        return result
