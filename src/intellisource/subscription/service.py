"""SubscriptionService — single business-logic entrypoint for yaml/API/CLI inputs.

All write paths (`POST /subscriptions`, `PATCH`, `DELETE`, `POST /reload`,
`POST /config/rollback/{version}`) and the equivalent CLI subcommands route
through this service. Validation, soft-delete semantics, version snapshot
recording, and rollback are centralized here so the three entrypoints stay
behaviourally identical.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.config.loader import ConfigVersionManager
from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.subscription_validator import SubscriptionValidator
from intellisource.storage.repositories.subscription import SubscriptionRepository

if TYPE_CHECKING:
    from intellisource.storage.models import Subscription


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
        self,
        limit: int = 20,
        cursor: str | None = None,
        *,
        channel: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Paginated list of subscriptions with optional channel/status filters."""
        return await self._repo.list(
            limit=limit, cursor=cursor, channel=channel, status=status
        )

    async def get(self, sub_id: uuid.UUID) -> Subscription | None:
        """Fetch a single subscription by id (or None when absent)."""
        return await self._repo.get_by_id(sub_id)

    async def list_versions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """List recorded config version snapshots, newest first."""
        return await self._version_manager.list_versions(self._session, limit=limit)

    async def diff_with_yaml(
        self, yaml_configs: list[SubscriptionConfig]
    ) -> dict[str, Any]:
        """Diff the yaml SSOT against current DB state (what a reload would do).

        Subscriptions reload is a full sync: names present in the DB but absent
        from yaml are soft-deleted (paused), hence ``db_only_action='pause'``.
        """
        yaml_names = {c.name for c in yaml_configs}
        db_names = await self._repo.list_names()
        return {
            "yaml_only": sorted(yaml_names - db_names),
            "db_only": sorted(db_names - yaml_names),
            "both": sorted(yaml_names & db_names),
            "db_only_action": "pause",
        }

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
        updated = await self._repo.update(sub_id, status="paused")
        return updated is not None

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
