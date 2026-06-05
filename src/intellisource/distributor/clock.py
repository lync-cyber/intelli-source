"""Shared injectable clock for distributor scheduling components.

A tiny seam so frequency / digest / periodic logic can be driven by a frozen
clock in tests instead of wall-clock ``datetime.now``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class DefaultClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)
