"""BaseDistributor abstract base class."""

from __future__ import annotations

import abc
import hashlib
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError

from intellisource.distributor.pii import mask_email, mask_phone

if TYPE_CHECKING:
    from intellisource.storage.repositories.push import PushRepository

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s-]{6,}\d")

_VALID_STATUSES = frozenset({"pending", "sent", "delivered", "failed"})


class BaseDistributor(abc.ABC):
    """Abstract base class for content distributors."""

    _push_repo: "PushRepository | None" = None

    @abc.abstractmethod
    async def distribute(self, content: Any, subscription: Any) -> Any:
        """Distribute content to a subscription."""

    async def check_dedup(
        self,
        subscription_id: Any,
        content_id: Any,
        channel: str,
        *,
        repo: "PushRepository",
    ) -> bool:
        """Return True if a push record already exists for this tuple."""
        return await repo.exists(subscription_id, content_id, channel)

    @staticmethod
    def _build_result(
        status: str,
        channel: str,
        content_id: Any,
        subscription_id: Any,
        **extra: Any,
    ) -> dict[str, Any]:
        """Build a push-result dict from the common skeleton plus channel extras.

        Each channel supplies its own status vocabulary and any channel-specific
        fields (e.g. ``pushed_at``, ``error``, ``error_code``) via ``extra``.
        """
        return {
            "status": status,
            "channel": channel,
            "content_id": content_id,
            "subscription_id": subscription_id,
            **extra,
        }

    def _mask_error_message(self, msg: str | None) -> str | None:
        """Redact any email addresses and phone numbers in *msg* before persistence."""
        if not msg:
            return msg
        masked = _EMAIL_RE.sub(lambda m: mask_email(m.group(0)), msg)
        masked = _PHONE_RE.sub(lambda m: mask_phone(m.group(0)), masked)
        return masked

    async def record_push(
        self,
        subscription_id: Any,
        content_id: Any,
        channel: str,
        *,
        status: str,
        retry_count: int = 0,
        error_message: str | None = None,
        extra_recipient: str | None = None,
        repo: "PushRepository",
    ) -> None:
        """Persist a push record; hashes any raw recipient value before storage."""
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid push record status {status!r};"
                f" must be one of {sorted(_VALID_STATUSES)}"
            )
        recipient_hash: str | None = None
        if extra_recipient is not None:
            recipient_hash = hashlib.sha256(extra_recipient.encode()).hexdigest()

        await repo.create(
            subscription_id=subscription_id,
            content_id=content_id,
            channel=channel,
            status=status,
            retry_count=retry_count,
            error_message=self._mask_error_message(error_message),
            recipient_hash=recipient_hash,
        )

    async def _check_dedup_if_repo(
        self,
        subscription_id: Any,
        content_id: Any,
        channel: str,
    ) -> bool:
        """Return True (duplicate) when a repo is configured and the record exists."""
        if self._push_repo is None:
            return False
        return await self.check_dedup(
            subscription_id, content_id, channel, repo=self._push_repo
        )

    async def _record_push_if_repo(
        self,
        subscription_id: Any,
        content_id: Any,
        channel: str,
        *,
        status: str,
        retry_count: int = 0,
        error_message: str | None = None,
        extra_recipient: str | None = None,
    ) -> None:
        """Persist a push record when a repo is configured."""
        if self._push_repo is None:
            return
        try:
            await self.record_push(
                subscription_id,
                content_id,
                channel,
                status=status,
                retry_count=retry_count,
                error_message=error_message,
                extra_recipient=extra_recipient,
                repo=self._push_repo,
            )
        except IntegrityError:
            # Concurrent dedup race — duplicate INSERT is the safe outcome (idempotent).
            pass

    async def _send_with_dedup_lifecycle(
        self,
        sub_id: Any,
        content_id: Any,
        channel: str,
        *,
        attempt_fn: Callable[
            [int, bool], Awaitable[tuple[bool, str | None, dict[str, Any]]]
        ],
        max_retry: int,
    ) -> tuple[bool, bool, int, str | None, dict[str, Any]]:
        """Shared dedup-check + retry-loop + record_push lifecycle for all channels.

        Each channel provides *attempt_fn(attempt_index, is_last_attempt)* which
        executes a single send attempt (including any inter-retry sleep) and returns
        ``(success, error_str_or_None, raw_api_result)``.  The raw_api_result dict
        is threaded back to the caller for channel-specific return value construction.

        Returns ``(was_deduplicated, succeeded, retry_count, error, raw_result)``.
        """
        if await self._check_dedup_if_repo(sub_id, content_id, channel):
            return True, False, 0, None, {}

        last_error: str | None = None
        last_raw: dict[str, Any] = {}
        for attempt in range(max_retry):
            is_last = attempt == max_retry - 1
            success, error, raw = await attempt_fn(attempt, is_last)
            last_raw = raw
            if success:
                await self._record_push_if_repo(
                    sub_id, content_id, channel, status="sent", retry_count=attempt
                )
                return False, True, attempt, None, raw
            last_error = error

        await self._record_push_if_repo(
            sub_id,
            content_id,
            channel,
            status="failed",
            retry_count=max_retry,
            error_message=last_error,
        )
        return False, False, max_retry, last_error, last_raw
