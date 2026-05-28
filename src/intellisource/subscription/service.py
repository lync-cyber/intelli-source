"""SubscriptionService — single business-logic entrypoint for yaml/API/CLI inputs.

All write paths (`POST /subscriptions`, `PATCH`, `DELETE`, `POST /reload`,
`POST /config/rollback/{version}`) and the equivalent CLI subcommands route
through this service. Validation, soft-delete semantics, version snapshot
recording, and rollback are centralized here so the three entrypoints stay
behaviourally identical.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.config.loader import ConfigVersionManager
from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.subscription_validator import SubscriptionValidator
from intellisource.storage.models import Subscription
from intellisource.storage.repositories.subscription import SubscriptionRepository


def build_subscription_version_manager() -> ConfigVersionManager:
    """Factory for the subscription-flavoured ConfigVersionManager."""
    return ConfigVersionManager(
        table_name="subscription_config_versions",
        config_cls=SubscriptionConfig,
    )


class SubscriptionService:
    """Business-logic facade over SubscriptionRepository + version manager.

    Constructed per request (FastAPI Depends) or per CLI invocation. Methods
    accept already-parsed SubscriptionConfig instances; the service runs the
    semantic validator (per-channel rules) before any persistence.
    """

    def __init__(
        self,
        session: AsyncSession,
        version_manager: ConfigVersionManager | None = None,
    ) -> None:
        self._session = session
        self._repo = SubscriptionRepository(session)
        self._validator = SubscriptionValidator()
        self._version_manager = (
            version_manager
            if version_manager is not None
            else build_subscription_version_manager()
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_paginated(
        self, limit: int = 20, cursor: str | None = None
    ) -> dict[str, Any]:
        """Paginated list of subscriptions (forwards to repository)."""
        return await self._repo.list(limit=limit, cursor=cursor)

    # ------------------------------------------------------------------
    # Single-record CRUD (API / CLI hot edits — no version snapshot)
    # ------------------------------------------------------------------

    async def create(self, cfg: SubscriptionConfig) -> Subscription:
        """Validate then create. Raises SubscriptionValidationError on bad input."""
        self._validator.validate(cfg)
        return await self._repo.create(
            name=cfg.name,
            channel=cfg.channel,
            channel_config=cfg.channel_config,
            match_rules=cfg.match_rules,
            frequency=cfg.frequency,
            quiet_hours=cfg.quiet_hours,
            timezone=cfg.timezone,
            discipline_tags=cfg.discipline_tags,
        )

    async def patch(
        self, sub_id: uuid.UUID, fields: dict[str, Any]
    ) -> Subscription | None:
        """Partial update by id. `fields` is exclude_unset dict from API/CLI body."""
        return await self._repo.update(sub_id, **fields)

    async def delete(self, sub_id: uuid.UUID) -> bool:
        """Soft delete: mark status='paused' to preserve push_records FK history."""
        existing = await self._repo.get_by_id(sub_id)
        if existing is None:
            return False
        existing.status = "paused"
        await self._session.flush()
        return True

    # ------------------------------------------------------------------
    # Bulk operations (yaml reload / rollback — write version snapshot)
    # ------------------------------------------------------------------

    async def bulk_sync_with_version(
        self,
        configs: list[SubscriptionConfig],
        *,
        author: str | None = None,
    ) -> dict[str, Any]:
        """Validate all → bulk_sync → record version snapshot atomically.

        Returns `{loaded_count, version, errors}`. On per-config validation
        failure the bad config is skipped and the error appended; on
        full-batch repository failure raises.
        """
        validated: list[SubscriptionConfig] = []
        errors: list[dict[str, Any]] = []
        for i, cfg in enumerate(configs):
            try:
                self._validator.validate(cfg)
                validated.append(cfg)
            except Exception as exc:
                errors.append({"index": i, "name": cfg.name, "error": str(exc)})

        await self._repo.bulk_sync_from_configs(validated)
        version_label = await self._version_manager.record_version_async(
            validated, session=self._session, author=author
        )
        return {
            "loaded_count": len(validated),
            "version": version_label,
            "errors": errors,
        }

    async def rollback_to_version(self, version_label: str) -> dict[str, Any]:
        """Restore subscriptions from a recorded snapshot then bulk_sync.

        Raises ValueError when the version label is unknown.
        """
        revived = await self._version_manager.rollback_by_label(
            version_label, session=self._session
        )
        typed: list[SubscriptionConfig] = []
        for cfg in revived:
            if isinstance(cfg, SubscriptionConfig):
                typed.append(cfg)
        await self._repo.bulk_sync_from_configs(typed)
        return {
            "rolled_back_to": version_label,
            "config_count": len(typed),
            "subscription_names": [c.name for c in typed],
        }
