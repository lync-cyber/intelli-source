"""DistributorFacade — orchestrates the 5-step distribution pipeline."""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any

from intellisource.core.settings import get_settings
from intellisource.distributor.pii import mask_email, mask_phone
from intellisource.observability.logging import get_logger

if TYPE_CHECKING:
    from intellisource.distributor.base import BaseDistributor
    from intellisource.distributor.matcher import SubscriptionMatcher

_logger = get_logger(__name__)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s-]{6,}\d")


def _mask_error_message(msg: str | None) -> str | None:
    """Redact email addresses and phone numbers in *msg* before persistence."""
    if not msg:
        return msg
    masked = _EMAIL_RE.sub(lambda m: mask_email(m.group(0)), msg)
    masked = _PHONE_RE.sub(lambda m: mask_phone(m.group(0)), masked)
    return masked


# B-005: distributor-layer labeled counter name.
_METRIC_PUSHES_TOTAL: str = "pushes_total"
_METRIC_PUSHES_DESC: str = "Push attempts by channel and outcome"


def _record_push_outcome(outcome: str, channel: str = "unknown") -> None:
    """Bump pushes_total{channel=..., status=...} in local + cross-process stores.

    distribute runs in the prefork worker, whose local MetricsCollector is never
    served over HTTP. The API ``/api/v1/metrics`` endpoint can therefore only
    surface this family by reading it back from the shared Redis store, so each
    outcome is mirrored there too (B-064). The two writes are independent — a
    failure in one must not skip the other.

    outcome ∈ {"sent", "failed", "skipped"}.
    """
    try:
        from intellisource.observability.metrics import MetricsCollector

        mc = MetricsCollector.get_instance()
        mc.increment_labeled_counter(
            _METRIC_PUSHES_TOTAL,
            labels={"channel": channel, "status": outcome},
        )
    except Exception:  # noqa: BLE001 — metric failures must not break delivery
        _logger.exception("failed to record push outcome metric")
    try:
        from intellisource.observability.shared_metrics import get_shared_metric_store

        get_shared_metric_store().increment_counter(
            _METRIC_PUSHES_TOTAL,
            labels={"channel": channel, "status": outcome},
            description=_METRIC_PUSHES_DESC,
        )
    except Exception:  # noqa: BLE001 — metric failures must not break delivery
        _logger.exception("failed to mirror push outcome metric to shared store")


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
        self._register_metrics()

    @property
    def channels(self) -> dict[str, BaseDistributor]:
        """Configured channel distributors, keyed by channel name."""
        return self._channels

    def _register_metrics(self) -> None:
        try:
            from intellisource.observability.metrics import MetricsCollector

            MetricsCollector.get_instance().register_labeled_counter(
                _METRIC_PUSHES_TOTAL,
                labelnames=["channel", "status"],
                description=_METRIC_PUSHES_DESC,
            )
        except Exception:  # noqa: BLE001 — metric failures must not break delivery
            _logger.exception("failed to register distributor metrics")
        try:
            from intellisource.observability.shared_metrics import (
                get_shared_metric_store,
            )

            # Register meta only (no unlabeled "" sample) so the API /metrics
            # endpoint lists pushes_total from worker boot, before the first push
            # records a labeled series. A seeded unlabeled sample would illegally
            # mix with the labeled samples this family emits.
            get_shared_metric_store().register_counter(
                _METRIC_PUSHES_TOTAL, _METRIC_PUSHES_DESC
            )
        except Exception:  # noqa: BLE001 — metric failures must not break delivery
            _logger.exception("failed to register distributor metrics in shared store")

    async def distribute(
        self,
        *,
        content_id: str,
        subscription_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute the 5-step distribution pipeline.

        Returns a dict with keys: status, matched, sent, skipped. When the
        referenced content cannot be loaded (invalid uuid / row missing)
        returns ``{"status": "failed", "reason": "content_not_found", ...}``
        so callers can distinguish a missing content from a content with
        zero matched subscriptions.
        """
        # Step 0: refresh DB-backed templates into the process-local registry so
        # a custom template created after this worker booted renders without a
        # restart (the render path resolves names from the in-memory registry).
        await self._hydrate_db_templates()

        # Step 1: load ProcessedContent from DB
        # Step 2: resolve subscriptions — both in one session to minimise round-trips
        content, subscriptions = await self._load_content_and_subscriptions(
            content_id=content_id,
            subscription_id=subscription_id,
        )
        if content is None:
            return {
                "status": "failed",
                "reason": "content_not_found",
                "content_id": content_id,
                "matched": 0,
                "sent": 0,
                "skipped": 0,
                "errors": [],
            }
        matched = self._matcher.match(content, subscriptions)

        sent = 0
        skipped = 0
        # Failure reasons per subscription so a channel-level bug (e.g. a raised
        # AttributeError) surfaces in the return value / task result instead of
        # being swallowed into an opaque skipped count.
        errors: list[dict[str, Any]] = []

        for sub in matched:
            channel_name: str = getattr(sub, "channel", "")
            channel = self._channels.get(channel_name)
            if channel is None:
                skipped += 1
                errors.append(
                    {
                        "subscription_id": str(getattr(sub, "id", "")),
                        "channel": channel_name or "unknown",
                        "reason": "channel not configured or disabled",
                    }
                )
                _record_push_outcome("skipped", channel=channel_name or "unknown")
                continue

            # Step 3: dedup gate
            already_pushed = await self._is_already_pushed(
                content_id=content_id,
                subscription_id=str(sub.id),
                channel=channel_name,
            )
            if already_pushed:
                skipped += 1
                _record_push_outcome("skipped", channel=channel_name)
                continue

            # Step 4: pre-push optimize (F-010) then channel.send
            push_content = await self._prepare_push_content(content, sub)
            try:
                outcome = await channel.distribute(push_content, sub)
            except Exception as exc:
                _logger.exception(
                    "channel.distribute failed for sub=%s channel=%s",
                    sub.id,
                    channel_name,
                )
                reason = str(exc) or type(exc).__name__
                skipped += 1
                errors.append(
                    {
                        "subscription_id": str(sub.id),
                        "channel": channel_name,
                        "reason": reason,
                    }
                )
                await self._record_failed_push(
                    content_id=content_id,
                    sub=sub,
                    channel=channel_name,
                    reason=reason,
                )
                continue

            # Channels swallow transport errors and return {"status": "failed"}
            # instead of raising, so the returned status — not just exceptions —
            # decides success.
            if isinstance(outcome, dict) and outcome.get("status") == "failed":
                reason = outcome.get("error") or "channel reported failure"
                _logger.warning(
                    "channel.distribute reported failure for sub=%s channel=%s: %s",
                    sub.id,
                    channel_name,
                    reason,
                )
                skipped += 1
                errors.append(
                    {
                        "subscription_id": str(sub.id),
                        "channel": channel_name,
                        "reason": reason,
                    }
                )
                await self._record_failed_push(
                    content_id=content_id,
                    sub=sub,
                    channel=channel_name,
                    reason=reason,
                )
                continue

            sent += 1
            _record_push_outcome("sent", channel=channel_name)

            # Step 5: record_push + PII mask
            recipient_raw = _extract_recipient(sub)
            await self._record_push(
                content_id=content_id,
                subscription_id=str(sub.id),
                channel=channel_name,
                recipient_id=_mask_recipient(recipient_raw),
                status="sent",
            )

        return {
            "status": "ok",
            "matched": len(matched),
            "sent": sent,
            "skipped": skipped,
            "errors": errors,
        }

    async def _hydrate_db_templates(self) -> None:
        """Register active DB templates into the in-memory digest registry.

        Best-effort: a templates-table error (e.g. an unmigrated DB) must never
        block delivery — built-in templates remain resolvable regardless. Built
        from ``storage`` + ``distributor.templates`` only, so the distributor
        stays below the template service in the layer graph.
        """
        from intellisource.distributor.templates.db_template import (
            register_db_templates,
        )
        from intellisource.storage.repositories.template import TemplateRepository

        try:
            async with self._session_factory() as session:
                rows = await TemplateRepository(session).list_active()
            register_db_templates(rows)
        except Exception:
            _logger.exception(
                "db template hydration failed; using in-memory registry only"
            )

    async def _prepare_push_content(self, content: Any, subscription: Any) -> Any:
        """Optimize content for push when enabled; degrade to original on failure."""
        if get_settings().push_optimize_enabled != "1":
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
        """Load ProcessedContent + matching subscriptions via ContentRepository.

        Opens one session so the eager-loaded ``raw_content.source`` (needed by
        SubscriptionMatcher for ``match_rules.source_names``, B-057) stays
        attached. A falsy ``subscription_id`` (None or "" from the strict
        distribute step, which has no subscription_id param) resolves to every
        active subscription rather than being treated as an invalid uuid; an
        unparseable id yields (None, []).
        """
        from intellisource.storage.repositories.content import ContentRepository

        try:
            content_uuid = uuid.UUID(content_id)
        except ValueError:
            return None, []

        sub_uuid: uuid.UUID | None = None
        if subscription_id:
            try:
                sub_uuid = uuid.UUID(subscription_id)
            except ValueError:
                return None, []

        async with self._session_factory() as session:
            repo = ContentRepository(session)
            return await repo.get_with_source_and_subscriptions(
                content_id=content_uuid, subscription_id=sub_uuid
            )

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

    async def _record_failed_push(
        self,
        *,
        content_id: str,
        sub: Any,
        channel: str,
        reason: str,
    ) -> None:
        """Record metric and persist a failed push record with masked PII."""
        _record_push_outcome("failed", channel=channel)
        recipient_raw = _extract_recipient(sub)
        await self._record_push(
            content_id=content_id,
            subscription_id=str(sub.id),
            channel=channel,
            recipient_id=_mask_recipient(recipient_raw),
            status="failed",
            error_message=_mask_error_message(reason),
        )

    async def _record_push(
        self,
        *,
        content_id: str,
        subscription_id: str,
        channel: str,
        recipient_id: str | None = None,
        status: str = "sent",
        error_message: str | None = None,
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
                    status=status,
                    recipient_id=recipient_id,
                    error_message=error_message,
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
