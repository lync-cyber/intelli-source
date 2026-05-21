"""BaseDistributor abstract base class."""

from __future__ import annotations

import abc
import hashlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from intellisource.storage.repositories.push import PushRepository


class BaseDistributor(abc.ABC):
    """Abstract base class for content distributors."""

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
