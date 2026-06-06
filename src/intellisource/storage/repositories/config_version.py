"""ConfigVersionRepository -- data access for config snapshot version tables.

Callers (the config-layer ``ConfigVersionManager``) pass a plain ``table_name``
string; the table -> ORM model mapping lives here so the config layer never
imports ``storage.models`` directly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.storage.models import ConfigVersion, SubscriptionConfigVersion

_VersionModel = type[ConfigVersion] | type[SubscriptionConfigVersion]

_TABLE_TO_MODEL: dict[str, _VersionModel] = {
    "config_versions": ConfigVersion,
    "subscription_config_versions": SubscriptionConfigVersion,
}


class ConfigVersionRepository:
    """CRUD for the two config-snapshot version tables, selected by name."""

    def __init__(self, session: AsyncSession, table_name: str) -> None:
        model = _TABLE_TO_MODEL.get(table_name)
        if model is None:
            raise ValueError(
                f"unknown config version table {table_name!r}; "
                f"must be one of {sorted(_TABLE_TO_MODEL)}"
            )
        self._session = session
        self._model = model

    async def insert_version(
        self, *, version: str, snapshot_yaml: str, author: str | None
    ) -> None:
        """Persist a snapshot row; no-op if the version label already exists.

        Mirrors the previous ``INSERT ... ON CONFLICT (version) DO NOTHING``.
        """
        existing = await self._session.scalar(
            select(self._model.id).where(self._model.version == version)
        )
        if existing is not None:
            return
        self._session.add(
            self._model(version=version, snapshot_yaml=snapshot_yaml, author=author)
        )
        await self._session.flush()

    async def list_versions(
        self, *, limit: int
    ) -> list[tuple[str, str | None, datetime | None, str]]:
        """Return ``(version, author, created_at, snapshot_yaml)`` newest-first.

        Ordered by the numeric value of ``version`` so "10" sorts after "9".
        """
        stmt = (
            select(
                self._model.version,
                self._model.author,
                self._model.created_at,
                self._model.snapshot_yaml,
            )
            .order_by(cast(self._model.version, Integer).desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [(row[0], row[1], row[2], row[3]) for row in result.all()]

    async def get_snapshot(self, version: str) -> str | None:
        """Return the snapshot yaml for *version*, or None when absent."""
        snapshot: str | None = await self._session.scalar(
            select(self._model.snapshot_yaml).where(self._model.version == version)
        )
        return snapshot
