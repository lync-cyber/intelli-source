"""TemplateService — single business entrypoint for custom digest templates.

Validates a :class:`TemplateConfig` (structural rules live on the config model;
the ``base_template`` must name a real built-in, checked here) and persists it
via :class:`TemplateRepository`. Mirrors ``SubscriptionService`` /
``SourceConfigService`` so the API / CLI / MCP / agent surfaces stay uniform.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.config.template_models import (
    TemplateConfig,
    TemplateValidationError,
)
from intellisource.storage.repositories.template import TemplateRepository

if TYPE_CHECKING:
    from intellisource.storage.models import Template


def _validate_base_template(name: str) -> None:
    """Ensure ``name`` references a real built-in digest template."""
    # Imported lazily so the service module carries no import-time edge to the
    # distributor package (and to avoid any registration-order coupling).
    from intellisource.distributor.templates import BUILTIN_TEMPLATE_NAMES

    if name not in BUILTIN_TEMPLATE_NAMES:
        raise TemplateValidationError(
            f"base_template {name!r} is not a known built-in template;"
            f" choose one of {sorted(BUILTIN_TEMPLATE_NAMES)}"
        )


def _reject_builtin_name(name: str) -> None:
    """Forbid a custom template name that would shadow a built-in template."""
    from intellisource.distributor.templates import BUILTIN_TEMPLATE_NAMES

    if name in BUILTIN_TEMPLATE_NAMES:
        raise TemplateValidationError(
            f"name {name!r} collides with a built-in template; choose another name"
        )


class TemplateService:
    """Business-logic facade over :class:`TemplateRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TemplateRepository(session)

    async def list_paginated(
        self, limit: int = 20, cursor: str | None = None
    ) -> dict[str, Any]:
        return await self._repo.list(limit=limit, cursor=cursor)

    async def list_active(self) -> Sequence[Template]:
        return await self._repo.list_active()

    async def get(self, template_id: uuid.UUID) -> Template | None:
        return await self._repo.get_by_id(template_id)

    async def get_by_name(self, name: str) -> Template | None:
        return await self._repo.get_by_name(name)

    async def create(self, cfg: TemplateConfig) -> Template:
        """Validate then upsert (by name). Raises TemplateValidationError."""
        _validate_base_template(cfg.base_template)
        _reject_builtin_name(cfg.name)
        return await self._repo.upsert(cfg)

    async def patch(
        self, template_id: uuid.UUID, fields: dict[str, Any]
    ) -> Template | None:
        """Partial update by id; validates ``base_template`` when present."""
        if "base_template" in fields:
            _validate_base_template(str(fields["base_template"]))
        return await self._repo.update(template_id, **fields)

    async def delete(self, template_id: uuid.UUID) -> bool:
        """Hard-delete a template by id (no inbound FK; safe to remove)."""
        return await self._repo.delete(template_id)


async def hydrate_template_registry(session: AsyncSession) -> int:
    """Load active custom templates into the in-process digest template registry.

    Called once at process startup (API lifespan + worker boot) so DB-backed
    templates are resolvable by the synchronous distribution render path
    alongside the built-ins. Returns the number of templates registered.
    """
    from intellisource.distributor.templates.db_template import register_db_templates

    rows = await TemplateService(session).list_active()
    return register_db_templates(rows)
