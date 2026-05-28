"""SourceConfigService — single business-logic entrypoint for sources yaml/API/CLI.

All write paths route through this service. Validation, soft-delete semantics,
version snapshot recording, and rollback are centralized here.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.config.loader import ConfigVersionManager
from intellisource.config.models import SourceConfig
from intellisource.config.validator import ConfigValidator
from intellisource.storage.models import Source
from intellisource.storage.repositories.source import SourceRepository


def build_source_version_manager() -> ConfigVersionManager:
    """Factory for the source-flavoured ConfigVersionManager."""
    return ConfigVersionManager(
        table_name="config_versions",
        config_cls=SourceConfig,
    )


class SourceConfigService:
    """Business-logic facade over SourceRepository + version manager.

    Constructed per request or per CLI invocation. Methods accept already-parsed
    SourceConfig instances; the service runs the semantic validator before any
    persistence.
    """

    def __init__(
        self,
        session: AsyncSession,
        version_manager: ConfigVersionManager | None = None,
    ) -> None:
        self._session = session
        self._repo = SourceRepository(session)
        self._validator = ConfigValidator()
        self._version_manager = (
            version_manager
            if version_manager is not None
            else build_source_version_manager()
        )

    # ------------------------------------------------------------------
    # Internal validation hook (patchable in tests)
    # ------------------------------------------------------------------

    def _validate_config(self, cfg: SourceConfig) -> SourceConfig:
        """Run semantic validation; raises on failure."""
        return self._validator.validate(cfg)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_paginated(
        self,
        limit: int = 20,
        cursor: str | None = None,
        *,
        type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        """Paginated list of sources with optional filters."""
        return await self._repo.list(
            limit=limit, cursor=cursor, type=type, status=status, tag=tag
        )

    # ------------------------------------------------------------------
    # Single-record CRUD (API / CLI hot edits — no version snapshot)
    # ------------------------------------------------------------------

    async def create(self, cfg: SourceConfig) -> Source:
        """Validate then upsert. Raises ConfigValidationError on bad input."""
        self._validate_config(cfg)
        return await self._repo.upsert(cfg)

    async def patch(
        self, source_id: uuid.UUID, fields: dict[str, Any]
    ) -> Source | None:
        """Partial update by id. `fields` is exclude_unset dict from API/CLI body.

        Maps the public `metadata` key to the ORM column name `metadata_`
        (SQLAlchemy reserves `metadata` on declarative_base).
        """
        if "metadata" in fields:
            fields = {**fields, "metadata_": fields.pop("metadata")}
        return await self._repo.update(source_id, **fields)

    async def delete(self, source_id: uuid.UUID) -> bool:
        """Soft delete: mark status='paused' to preserve FK history."""
        existing = await self._repo.get_by_id(source_id)
        if existing is None:
            return False
        existing.status = "paused"
        await self._session.flush()
        return True

    # ------------------------------------------------------------------
    # Bulk operations (yaml reload — additive upsert + version snapshot)
    # ------------------------------------------------------------------

    async def bulk_sync_with_version(
        self,
        configs: list[SourceConfig],
        *,
        author: str | None = None,
    ) -> dict[str, Any]:
        """Validate all → bulk_upsert → record version snapshot.

        Returns `{loaded_count, version, errors}`. On per-config validation
        failure the bad config is skipped and the error appended.

        Uses bulk_upsert (additive) rather than bulk_sync_from_configs so that
        sources created via the API are not soft-deleted by a yaml reload.
        """
        validated: list[SourceConfig] = []
        errors: list[dict[str, Any]] = []
        for i, cfg in enumerate(configs):
            try:
                validated.append(self._validate_config(cfg))
            except Exception as exc:
                errors.append({"index": i, "name": cfg.name, "error": str(exc)})

        if validated:
            await self._repo.bulk_upsert(validated)

        version_label = await self._version_manager.record_version_async(
            validated, session=self._session, author=author
        )
        return {
            "loaded_count": len(validated),
            "version": version_label,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Rollback (full sync from snapshot — overwrites DB to match snapshot)
    # ------------------------------------------------------------------

    async def rollback_to_version(self, version_label: str) -> dict[str, Any]:
        """Restore sources from a recorded snapshot via full sync.

        Raises ValueError when the version label is unknown.
        Uses bulk_sync_from_configs (full sync with soft-delete) so the DB
        state precisely matches the snapshot.
        """
        revived = await self._version_manager.rollback_by_label(
            version_label, session=self._session
        )
        typed: list[SourceConfig] = []
        for cfg in revived:
            if isinstance(cfg, SourceConfig):
                typed.append(cfg)
        await self._repo.bulk_sync_from_configs(typed)
        return {
            "rolled_back_to": version_label,
            "config_count": len(typed),
            "source_names": [c.name for c in typed],
        }
