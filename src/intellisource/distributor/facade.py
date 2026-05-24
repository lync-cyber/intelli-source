"""DistributorFacade — orchestrates the 5-step distribution pipeline."""

from __future__ import annotations

import logging
import os
import uuid
from typing import TYPE_CHECKING, Any

from intellisource.distributor.pii import mask_email, mask_phone

if TYPE_CHECKING:
    from intellisource.distributor.base import BaseDistributor
    from intellisource.distributor.matcher import SubscriptionMatcher

_logger = logging.getLogger(__name__)


class DistributorFacade:
    """Orchestrates content distribution through the 5-step pipeline.

    Steps:
    1. Load ProcessedContent from DB by content_id.
    2. SubscriptionMatcher.match to find applicable subscriptions.
    3. Dedup gate — skip subscriptions already pushed.
    4. channel.distribute for each matched, non-deduped subscription.
    5. _record_push + PII mask for persistence.

    F-010 / AC-047~049: when ``IS_PUSH_OPTIMIZE_ENABLED=1`` and an
    ``llm_gateway`` is wired in, content is optimized *before*
    ``channel.distribute`` (truncate + optional LLM; failures degrade to
    original content).
    """

    def __init__(
        self,
        session_factory: Any,
        matcher: SubscriptionMatcher,
        channels: dict[str, BaseDistributor],
        llm_gateway: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._matcher = matcher
        self._channels = channels
        self._llm_gateway = llm_gateway

    async def distribute(
        self,
        *,
        content_id: str,
        subscription_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute the 5-step distribution pipeline.

        Returns a dict with keys: status, matched, sent, skipped.
        """
        # Step 1: load ProcessedContent from DB
        # Step 2: resolve subscriptions — both in one session to minimise round-trips
        content, subscriptions = await self._load_content_and_subscriptions(
            content_id=content_id,
            subscription_id=subscription_id,
        )
        matched = self._matcher.match(content, subscriptions)

        sent = 0
        skipped = 0

        for sub in matched:
            channel_name: str = getattr(sub, "channel", "")
            channel = self._channels.get(channel_name)
            if channel is None:
                skipped += 1
                continue

            # Step 3: dedup gate
            already_pushed = await self._is_already_pushed(
                content_id=content_id,
                subscription_id=str(sub.id),
                channel=channel_name,
            )
            if already_pushed:
                skipped += 1
                continue

            # Step 4: pre-push optimize (F-010) then channel.send
            push_content = await self._prepare_push_content(content, sub)
            try:
                await channel.distribute(push_content, sub)
                sent += 1
            except Exception:
                _logger.exception(
                    "channel.distribute failed for sub=%s channel=%s",
                    sub.id,
                    channel_name,
                )
                skipped += 1
                continue

            # Step 5: record_push + PII mask
            recipient_raw = _extract_recipient(sub)
            await self._record_push(
                content_id=content_id,
                subscription_id=str(sub.id),
                channel=channel_name,
                recipient_id=_mask_recipient(recipient_raw),
            )

        return {
            "status": "ok",
            "matched": len(matched),
            "sent": sent,
            "skipped": skipped,
        }

    async def _prepare_push_content(self, content: Any, subscription: Any) -> Any:
        """Optimize content for push when enabled; degrade to original on failure."""
        if os.environ.get("IS_PUSH_OPTIMIZE_ENABLED") != "1":
            return content
        if self._llm_gateway is None:
            return content
        from intellisource.distributor.push_optimizer import optimize_for_push

        try:
            return await optimize_for_push(content, subscription, self._llm_gateway)
        except Exception:
            _logger.exception("push optimize failed, using original content (AC-049)")
            return content

    async def _load_content_and_subscriptions(
        self,
        *,
        content_id: str,
        subscription_id: str | None,
    ) -> tuple[Any, list[Any]]:
        """Load ProcessedContent and resolve subscriptions in a single session."""
        from intellisource.storage.models import ProcessedContent, Subscription

        try:
            content_uuid = uuid.UUID(content_id)
        except ValueError:
            return None, []

        async with self._session_factory() as session:
            # Step 1: load content
            content = await session.get(ProcessedContent, content_uuid)

            # Step 2: resolve subscriptions via SELECT (never session.get)
            from sqlalchemy import select

            if subscription_id is None:
                stmt = select(Subscription).where(Subscription.status == "active")
            else:
                try:
                    sub_uuid = uuid.UUID(subscription_id)
                except ValueError:
                    return None, []
                stmt = select(Subscription).where(Subscription.id == sub_uuid)

            result = await session.scalars(stmt)
            subscriptions: list[Any] = list(result.all())

        return content, subscriptions

    async def _is_already_pushed(
        self,
        *,
        content_id: str,
        subscription_id: str,
        channel: str,
    ) -> bool:
        """Return True if a PushRecord already exists for this tuple."""
        from intellisource.storage.repositories.push import PushRepository

        try:
            content_uuid = uuid.UUID(content_id)
            sub_uuid = uuid.UUID(subscription_id)
        except ValueError:
            return False

        async with self._session_factory() as session:
            repo = PushRepository(session=session)
            return await repo.exists(sub_uuid, content_uuid, channel)

    async def _record_push(
        self,
        *,
        content_id: str,
        subscription_id: str,
        channel: str,
        recipient_id: str | None = None,
    ) -> None:
        """Persist a push record with masked recipient info."""
        from intellisource.storage.repositories.push import PushRepository

        try:
            content_uuid = uuid.UUID(content_id)
            sub_uuid = uuid.UUID(subscription_id)
        except ValueError:
            return

        async with self._session_factory() as session:
            repo = PushRepository(session=session)
            try:
                await repo.create(
                    subscription_id=sub_uuid,
                    content_id=content_uuid,
                    channel=channel,
                    status="sent",
                    recipient_id=recipient_id,
                )
                await session.commit()
            except Exception as exc:
                from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

                if isinstance(exc, IntegrityError):
                    # Channel layer already recorded; idempotent skip
                    pass
                else:
                    raise


def _extract_recipient(sub: Any) -> str:
    """Extract the raw recipient identifier from subscription channel_config."""
    cfg: dict[str, Any] = getattr(sub, "channel_config", {}) or {}
    channel: str = getattr(sub, "channel", "")
    if channel == "email":
        return str(cfg.get("to_addr", ""))
    if channel == "wechat":
        return str(cfg.get("openid", ""))
    if channel == "wework":
        return str(cfg.get("user_id", ""))
    return ""


def _mask_recipient(raw: str) -> str | None:
    """Mask PII in recipient.

    Email/phone are masked; opaque platform IDs (wechat openid, wework user_id)
    pass through as they are not traditional PII.
    """
    if not raw:
        return None
    if "@" in raw:
        return mask_email(raw)
    # phone-like: 11+ digits
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) >= 7:
        return mask_phone(raw)
    return raw
