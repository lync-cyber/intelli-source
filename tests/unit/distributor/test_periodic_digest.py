"""WF-5.3c: digest_window_start helper + PeriodicDigestRunner.run orchestration.

The DB-touching methods (_periodic_subscriptions / _window_contents / _dispatch)
are overridden with stubs here; they are validated end-to-end by the real-stack /
integration path. These tests cover the pure window math and the run() loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from intellisource.distributor.digest_dispatch import DispatchResult
from intellisource.distributor.periodic import (
    PeriodicDigestRunner,
    digest_window_start,
)

NOW = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)


class _FixedClock:
    def now(self) -> datetime:
        return NOW


@dataclass
class _Sub:
    id: str = "s1"
    frequency: str = "daily"
    last_sent_at: datetime | None = None


class TestWindowStart:
    def test_uses_last_sent_at_when_set(self) -> None:
        last = NOW - timedelta(hours=30)
        assert digest_window_start(_Sub(last_sent_at=last), NOW) == last

    def test_daily_first_run_is_one_day_before_now(self) -> None:
        assert digest_window_start(_Sub(frequency="daily"), NOW) == NOW - timedelta(
            days=1
        )

    def test_weekly_first_run_is_seven_days_before_now(self) -> None:
        assert digest_window_start(_Sub(frequency="weekly"), NOW) == NOW - timedelta(
            days=7
        )


@dataclass
class _StubRunner(PeriodicDigestRunner):
    """Overrides the three I/O seams so run()'s loop can be tested in-memory."""

    subs: list[Any] = field(default_factory=list)
    contents: list[Any] = field(default_factory=list)
    results: list[DispatchResult] = field(default_factory=list)
    windows: list[datetime] = field(default_factory=list)
    dispatched: list[tuple[Any, list[Any]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._clock = _FixedClock()

    async def _periodic_subscriptions(self) -> list[Any]:
        return self.subs

    async def _window_contents(self, window_start: datetime) -> list[Any]:
        self.windows.append(window_start)
        return self.contents

    async def _dispatch(self, subscription: Any, contents: list[Any]) -> DispatchResult:
        self.dispatched.append((subscription, contents))
        return self.results.pop(0)


def _res(status: str) -> DispatchResult:
    return DispatchResult(status=status, channel="email", content_count=1)


class TestRun:
    async def test_dispatches_each_sub_and_tallies_outcomes(self) -> None:
        subs = [_Sub(id="a", frequency="daily"), _Sub(id="b", frequency="weekly")]
        runner = _StubRunner(
            subs=subs,
            contents=[object()],
            results=[_res("sent"), _res("skipped")],
        )
        summary = await runner.run()

        assert summary["subscriptions"] == 2
        assert summary["sent"] == 1
        assert summary["skipped"] == 1
        assert summary["failed"] == 0
        assert len(runner.dispatched) == 2

    async def test_window_start_computed_per_subscription(self) -> None:
        last = NOW - timedelta(hours=40)
        subs = [_Sub(id="a", frequency="daily", last_sent_at=last)]
        runner = _StubRunner(subs=subs, contents=[], results=[_res("sent")])
        await runner.run()
        # The daily sub with a watermark opens its window at last_sent_at.
        assert runner.windows == [last]

    async def test_empty_subscriptions_is_a_noop_summary(self) -> None:
        runner = _StubRunner(subs=[], results=[])
        summary = await runner.run()
        assert summary == {
            "subscriptions": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 0,
        }
