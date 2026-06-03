"""SubscriptionRepository -- data access for Subscription entities."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from intellisource.config.subscription_models import SubscriptionConfig
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

    async def upsert(self, config: SubscriptionConfig) -> Subscription:
        """Create or update a Subscription from a SubscriptionConfig (by name).

        Existing subscription whose name matches the config is updated in-place;
        otherwise a new Subscription is created with status='active'.
        """
        stmt = select(Subscription).where(Subscription.name == config.name)
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.channel = config.channel
            existing.channel_config = config.channel_config
            existing.match_rules = config.match_rules
            existing.frequency = config.frequency
            existing.quiet_hours = config.quiet_hours
            existing.timezone = config.timezone
            existing.discipline_tags = config.discipline_tags
            # Re-activate previously paused subscriptions when reintroduced in yaml
            if existing.status == "paused":
                existing.status = "active"
            await self._session.flush()
            # Refresh so the onupdate ``updated_at`` (expired after the UPDATE
            # flush) is repopulated within the async greenlet; a later sync
            # attribute access on the returned row would otherwise raise
            # MissingGreenlet.
            await self._session.refresh(existing)
            return existing
        subscription = Subscription(
            name=config.name,
            channel=config.channel,
            channel_config=config.channel_config,
            match_rules=config.match_rules,
            frequency=config.frequency,
            quiet_hours=config.quiet_hours,
            timezone=config.timezone,
            discipline_tags=config.discipline_tags,
            status="active",
        )
        self._session.add(subscription)
        await self._session.flush()
        return subscription

    async def bulk_sync_from_configs(
        self, configs: Sequence[SubscriptionConfig]
    ) -> None:
        """Sync the full set of subscription configs to the database (by name).

        Creates new subscriptions, updates existing ones, and marks subscriptions
        absent from *configs* as status='paused' (soft-delete to preserve
        push_records FK history).
        """
        config_by_name: dict[str, SubscriptionConfig] = {c.name: c for c in configs}

        result = await self._session.execute(select(Subscription))
        existing_subs: Sequence[Subscription] = result.scalars().all()
        existing_by_name: dict[str, Subscription] = {s.name: s for s in existing_subs}

        for name, cfg in config_by_name.items():
            if name in existing_by_name:
                existing = existing_by_name[name]
                existing.channel = cfg.channel
                existing.channel_config = cfg.channel_config
                existing.match_rules = cfg.match_rules
                existing.frequency = cfg.frequency
                existing.quiet_hours = cfg.quiet_hours
                existing.timezone = cfg.timezone
                existing.discipline_tags = cfg.discipline_tags
                if existing.status == "paused":
                    existing.status = "active"
            else:
                self._session.add(
                    Subscription(
                        name=cfg.name,
                        channel=cfg.channel,
                        channel_config=cfg.channel_config,
                        match_rules=cfg.match_rules,
                        frequency=cfg.frequency,
                        quiet_hours=cfg.quiet_hours,
                        timezone=cfg.timezone,
                        discipline_tags=cfg.discipline_tags,
                        status="active",
                    )
                )

        for name, sub in existing_by_name.items():
            if name not in config_by_name:
                sub.status = "paused"

        await self._session.flush()
