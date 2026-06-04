"""Periodic (daily/weekly) digest run — the worker-side I/O orchestration.

Ties the pure pieces together against the real database: load the active
daily/weekly subscriptions, open each one's delivery window, fetch the content
that landed in it, then assemble + dispatch one digest per subscription
(recording PushRecords and advancing ``last_sent_at`` via DigestDispatcher).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from intellisource.distributor.digest import DigestAssembler
from intellisource.distributor.digest_dispatch import DigestDispatcher, DispatchResult
from intellisource.distributor.digest_enhance import DigestEnhancer
from intellisource.distributor.frequency import FrequencyController
from intellisource.distributor.llm_renderer import LLMRenderer
from intellisource.observability.logging import get_logger
from intellisource.storage.models import ProcessedContent, RawContent, Subscription
from intellisource.storage.repositories.push import PushRepository
from intellisource.storage.repositories.subscription import SubscriptionRepository

_logger = get_logger(__name__)

_PERIODIC_FREQUENCIES: tuple[str, ...] = ("daily", "weekly")

_WINDOW_INTERVALS: dict[str, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}

_WINDOW_CONTENT_LIMIT = 200


class _Clock(Protocol):
    def now(self) -> datetime: ...


class _DefaultClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def digest_window_start(subscription: Any, now: datetime) -> datetime:
    """Return the start of the delivery window for *subscription*.

    Picks up where the last digest left off (``last_sent_at``); on the first
    ever run, falls back to one frequency-interval before *now*.
    """
    last_sent: datetime | None = getattr(subscription, "last_sent_at", None)
    if last_sent is not None:
        return last_sent
    interval = _WINDOW_INTERVALS.get(
        getattr(subscription, "frequency", ""), timedelta(days=1)
    )
    return now - interval


class PeriodicDigestRunner:
    """Assemble + dispatch periodic digests for every due subscription."""

    def __init__(
        self,
        *,
        session_factory: Any,
        channels: dict[str, Any],
        llm_gateway: Any = None,
        clock: _Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock: _Clock = clock or _DefaultClock()
        enhancer = DigestEnhancer(llm_gateway) if llm_gateway is not None else None
        llm_renderer = LLMRenderer(llm_gateway) if llm_gateway is not None else None
        # Share the one clock with the assembler's frequency gate so the
        # due-check, the delivery window, and the last_sent_at watermark all
        # agree on "now" (otherwise should_send_now silently uses wall-clock).
        self._dispatcher = DigestDispatcher(
            assembler=DigestAssembler(
                frequency=FrequencyController(clock=self._clock),
                enhancer=enhancer,
                llm_renderer=llm_renderer,
            ),
            channels=channels,
            clock=self._clock,
        )

    async def run(self) -> dict[str, int]:
        """Process every active daily/weekly subscription; return an outcome tally."""
        summary: dict[str, int] = {
            "subscriptions": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 0,
        }
        for sub in await self._periodic_subscriptions():
            window_start = digest_window_start(sub, self._clock.now())
            contents = await self._window_contents(window_start)
            result = await self._dispatch(sub, contents)
            summary["subscriptions"] += 1
            summary[result.status] = summary.get(result.status, 0) + 1
        _logger.info(
            "periodic digest run complete: %d subs, %d sent, %d skipped, %d failed",
            summary["subscriptions"],
            summary["sent"],
            summary["skipped"],
            summary["failed"],
        )
        return summary

    async def _periodic_subscriptions(self) -> list[Any]:
        """Load active subscriptions whose frequency is daily or weekly."""
        async with self._session_factory() as session:
            stmt = select(Subscription).where(
                Subscription.status == "active",
                Subscription.frequency.in_(_PERIODIC_FREQUENCIES),
            )
            return list((await session.scalars(stmt)).all())

    async def _window_contents(self, window_start: datetime) -> list[Any]:
        """Fetch content that entered the system since *window_start*.

        ``raw_content.source`` is eager-loaded so SubscriptionMatcher can read
        ``source_names`` without a lazy load on the detached rows.
        """
        async with self._session_factory() as session:
            stmt = (
                select(ProcessedContent)
                .where(ProcessedContent.created_at >= window_start)
                .options(
                    selectinload(ProcessedContent.raw_content).selectinload(
                        RawContent.source
                    )
                )
                .order_by(ProcessedContent.created_at)
                .limit(_WINDOW_CONTENT_LIMIT)
            )
            return list((await session.scalars(stmt)).all())

    async def _dispatch(self, subscription: Any, contents: list[Any]) -> DispatchResult:
        """Dispatch one subscription's digest within a fresh, committed session."""
        async with self._session_factory() as session:
            push_repo = PushRepository(session=session)
            subscription_repo = SubscriptionRepository(session=session)
            result = await self._dispatcher.dispatch(
                subscription,
                contents,
                push_repo=push_repo,
                subscription_repo=subscription_repo,
            )
            await session.commit()
            return result


__all__ = ["PeriodicDigestRunner", "digest_window_start"]
