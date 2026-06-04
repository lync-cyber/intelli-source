"""TemplateRepository — data access for :class:`Template` entities."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from intellisource.config.template_models import TemplateConfig
from intellisource.storage.models import Template
from intellisource.storage.repositories.base import BaseRepository


class TemplateRepository(BaseRepository[Template]):
    """CRUD + name lookup for :class:`Template` entities."""

    _model_class = Template

    async def get_by_name(self, name: str) -> Template | None:
        stmt = select(Template).where(Template.name == name)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(self, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        return await self._paginate(select(Template), limit=limit, cursor=cursor)

    async def list_active(self) -> Sequence[Template]:
        stmt = select(Template).where(Template.status == "active")
        return list((await self._session.execute(stmt)).scalars().all())

    async def upsert(self, config: TemplateConfig) -> Template:
        """Create or update a Template from a TemplateConfig (by name)."""
        stmt = select(Template).where(Template.name == config.name)
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.base_template = config.base_template
            existing.formats = list(config.formats)
            existing.default_format = config.default_format
            existing.jinja_source = dict(config.jinja_source)
            existing.aggregate_config = dict(config.aggregate_config)
            existing.status = config.status
            await self._session.flush()
            # Refresh so the onupdate ``updated_at`` (expired after the UPDATE
            # flush) is repopulated within the async greenlet; a later sync
            # attribute access on the returned row would otherwise raise
            # MissingGreenlet.
            await self._session.refresh(existing)
            return existing
        template = Template(
            name=config.name,
            base_template=config.base_template,
            formats=list(config.formats),
            default_format=config.default_format,
            jinja_source=dict(config.jinja_source),
            aggregate_config=dict(config.aggregate_config),
            status=config.status,
        )
        self._session.add(template)
        await self._session.flush()
        await self._session.refresh(template)
        return template
