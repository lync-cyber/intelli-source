"""SubscriptionRepository -- data access for Subscription entities."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from intellisource.storage.models import Subscription
from intellisource.storage.repositories.base import BaseRepository


class SubscriptionRepository(BaseRepository[Subscription]):
    """CRUD and filtered listing for :class:`Subscription` entities."""

    _model_class = Subscription

    async def create(
        self,
        name: str,
        channel: str,
        channel_config: dict[str, Any],
        match_rules: dict[str, Any],
        source_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> Subscription:
        return await self._create_entity(
            name=name,
            channel=channel,
            channel_config=channel_config,
            match_rules=match_rules,
            source_id=source_id,
            **kwargs,
        )

    async def list(
        self,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        stmt = select(Subscription)
        return await self._paginate(stmt, limit=limit, cursor=cursor)
