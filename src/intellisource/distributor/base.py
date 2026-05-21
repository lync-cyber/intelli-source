"""BaseDistributor abstract base class."""

from __future__ import annotations

import abc
import hashlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from intellisource.storage.repositories.push import PushRepository


class BaseDistributor(abc.ABC):
    """Abstract base class for content distributors."""

    _push_repo: "PushRepository | None"

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
        recipient_hash: str | None = None
        if extra_recipient is not None:
            recipient_hash = hashlib.sha256(extra_recipient.encode()).hexdigest()

        await repo.create(
            subscription_id=subscription_id,
            content_id=content_id,
            channel=channel,
            status=status,
            retry_count=retry_count,
            error_message=error_message,
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
                    sub_id, content_id, channel, status="success"
                )
                return False, True, 0, None, raw
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
