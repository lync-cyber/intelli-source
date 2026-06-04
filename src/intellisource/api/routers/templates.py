"""Templates API router: CRUD for custom digest templates + catalog detail.

A thin shell over :class:`TemplateService`. Custom templates are keyed by
``name`` (the same key subscriptions reference in ``channel_config.template``),
mirroring the pipelines router. The single-read endpoint also surfaces the
built-in catalog entries so an LLM/user can inspect any resolvable template.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.api.errors import error_json
from intellisource.api.schemas.templates import TemplateDetail
from intellisource.config.template_models import TemplateConfig, TemplateValidationError
from intellisource.distributor.templates import (
    BUILTIN_TEMPLATE_NAMES,
    TEMPLATE_REGISTRY,
)
from intellisource.template.service import TemplateService

router = APIRouter(tags=["templates"])


def _get_service(
    session: AsyncSession = Depends(get_db_session),
) -> TemplateService:
    return TemplateService(session)


class TemplatePatchRequest(BaseModel):
    """Partial-update body for PATCH /templates/{name} (name is immutable)."""

    base_template: str | None = None
    formats: list[str] | None = None
    default_format: str | None = None
    jinja_source: dict[str, str] | None = None
    aggregate_config: dict[str, Any] | None = None
    status: str | None = None


def _serialize_row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "source": "db",
        "base_template": row.base_template,
        "formats": list(row.formats),
        "default_format": row.default_format,
        "jinja_source": dict(row.jinja_source),
        "aggregate_config": dict(row.aggregate_config),
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/templates/{name}", response_model=TemplateDetail)
async def get_template_detail(
    name: str,
    service: TemplateService = Depends(_get_service),
) -> Any:
    """Return a custom template's full definition, or a built-in catalog entry."""
    row = await service.get_by_name(name)
    if row is not None:
        return _serialize_row(row)
    builtin = TEMPLATE_REGISTRY.get(name)
    if builtin is not None and name in BUILTIN_TEMPLATE_NAMES:
        return {
            "name": name,
            "source": "builtin",
            "formats": sorted(builtin.formats),
            "default_format": builtin.default_format,
        }
    return error_json(404, "not found")


@router.post(
    "/templates", status_code=status.HTTP_201_CREATED, response_model=TemplateDetail
)
async def create_template(
    body: TemplateConfig,
    service: TemplateService = Depends(_get_service),
) -> Any:
    """Create or replace a custom digest template (idempotent upsert by name)."""
    try:
        created = await service.create(body)
    except TemplateValidationError as exc:
        return error_json(422, str(exc))
    return _serialize_row(created)


@router.patch("/templates/{name}", response_model=TemplateDetail)
async def update_template(
    name: str,
    body: TemplatePatchRequest,
    service: TemplateService = Depends(_get_service),
) -> Any:
    """Partial-update a custom template; 404 if absent, 422 if invalid."""
    row = await service.get_by_name(name)
    if row is None:
        return error_json(404, "not found")
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = await service.patch(row.id, fields)
    except TemplateValidationError as exc:
        return error_json(422, str(exc))
    if updated is None:
        return error_json(404, "not found")
    return _serialize_row(updated)


@router.delete("/templates/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    name: str,
    service: TemplateService = Depends(_get_service),
) -> Response:
    """Delete a custom template by name; 404 if absent (built-ins are immutable)."""
    row = await service.get_by_name(name)
    if row is None:
        return error_json(404, "not found")
    await service.delete(row.id)
    return Response(status_code=204)
