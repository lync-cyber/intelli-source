"""DigestDispatcher — assemble + send a periodic digest for one subscription.

Given a subscription and the candidate content rows for its delivery window,
assemble one digest (via :class:`DigestAssembler`), send it once on the
subscription's channel (``channel.send_rendered``), then record one PushRecord
per delivered content (deduplicated) and advance the subscription's
``last_sent_at`` watermark. The DB query that produces the window content and
the session/repository wiring live in the beat task; this class is the pure
per-subscription orchestration over injected collaborators.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from intellisource.distributor.clock import Clock, DefaultClock
from intellisource.distributor.digest import DigestAssembler, DigestPayload
from intellisource.observability.logging import get_logger

_logger = get_logger(__name__)


@dataclass
class DispatchResult:
    """Outcome of dispatching one subscription's periodic digest."""

    status: str  # "sent" | "skipped" | "failed"
    channel: str = ""
    content_count: int = 0
    reason: str | None = None


class DigestDispatcher:
    """Per-subscription periodic-digest orchestration over injected collaborators."""

    def __init__(
        self,
        *,
        assembler: DigestAssembler,
        channels: dict[str, Any],
        clock: Clock | None = None,
    ) -> None:
        self._assembler = assembler
        self._channels = channels
        self._clock: Clock = clock or DefaultClock()

    async def dispatch(
        self,
        subscription: Any,
        contents: list[Any],
        *,
        push_repo: Any,
        subscription_repo: Any,
    ) -> DispatchResult:
        """Assemble, send, record, and advance the watermark for *subscription*.

        Returns a ``skipped`` result when the subscription is not due / has no
        matching content / targets a channel that is unconfigured or cannot
        render digests; ``failed`` when the channel send fails (watermark is not
        advanced, so the next run retries the same window).
        """
        payload = await self._assembler.assemble(subscription, contents)
        if payload is None:
            return DispatchResult(status="skipped", reason="not_due_or_no_content")

        channel_name = payload.channel
        channel = self._channels.get(channel_name)
        if channel is None:
            return DispatchResult(
                status="skipped",
                channel=channel_name,
                reason="channel_not_configured",
            )

        try:
            result = await channel.send_rendered(
                subscription,
                title=payload.title,
                body=payload.body,
                fmt=payload.fmt,
            )
        except NotImplementedError:
            return DispatchResult(
                status="skipped",
                channel=channel_name,
                reason="channel_unsupported",
            )

        if result.get("status") != "sent":
            return DispatchResult(
                status="failed",
                channel=channel_name,
                reason=str(result.get("error") or "channel reported failure"),
            )

        recorded = await self._record(payload, channel_name, push_repo)
        await subscription_repo.update(
            self._sub_uuid(subscription), last_sent_at=self._clock.now()
        )
        _logger.info(
            "digest sent sub=%s channel=%s contents=%d",
            getattr(subscription, "id", ""),
            channel_name,
            recorded,
        )
        return DispatchResult(
            status="sent", channel=channel_name, content_count=recorded
        )

    async def _record(
        self, payload: DigestPayload, channel_name: str, push_repo: Any
    ) -> int:
        """Persist one PushRecord per delivered content, skipping duplicates."""
        sub_uuid = self._sub_uuid(payload.subscription)
        recorded = 0
        for cid in payload.content_ids:
            try:
                content_uuid = uuid.UUID(cid)
            except (ValueError, TypeError):
                continue
            if await push_repo.exists(sub_uuid, content_uuid, channel_name):
                continue
            await push_repo.create(
                subscription_id=sub_uuid,
                content_id=content_uuid,
                channel=channel_name,
                status="sent",
                render_mode=payload.render_mode,
            )
            recorded += 1
        return recorded

    @staticmethod
    def _sub_uuid(subscription: Any) -> uuid.UUID:
        return uuid.UUID(str(getattr(subscription, "id", "")))
