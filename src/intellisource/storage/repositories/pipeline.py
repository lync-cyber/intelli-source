"""PipelineRepository -- data access for Pipeline definitions + ordered steps."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from intellisource.config.pipeline_models import PipelineConfig
from intellisource.storage.models import Pipeline, PipelineStep
from intellisource.storage.repositories.base import BaseRepository


def _steps_from_config(config: PipelineConfig) -> list[PipelineStep]:
    """Materialize ordered PipelineStep rows from a config's step list."""
    return [
        PipelineStep(position=i, definition=dict(step))
        for i, step in enumerate(config.steps)
    ]


class PipelineRepository(BaseRepository[Pipeline]):
    """CRUD + name lookup for :class:`Pipeline` definition headers and steps."""

    _model_class = Pipeline

    def _apply_header(self, pipeline: Pipeline, config: PipelineConfig) -> None:
        pipeline.mode = config.mode
        pipeline.max_steps = config.max_steps
        pipeline.on_failure = config.on_failure
        pipeline.agent_mode = config.agent_mode
        pipeline.system_prompt = config.system_prompt
        pipeline.max_tokens_budget = config.max_tokens_budget
        pipeline.tools_allowed = list(config.tools_allowed)
        pipeline.tools_denied = list(config.tools_denied)
        pipeline.tool_permissions = dict(config.tool_permissions)

    async def upsert(self, config: PipelineConfig) -> Pipeline:
        """Create or update a Pipeline (by name); steps are fully replaced.

        Existing steps are loaded so reassigning the collection triggers
        delete-orphan rather than leaving stale rows behind.
        """
        stmt = (
            select(Pipeline)
            .where(Pipeline.name == config.name)
            .options(selectinload(Pipeline.steps))
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()

        if existing is not None:
            self._apply_header(existing, config)
            # Delete the old steps before inserting new ones so a reused
            # (pipeline_id, position) does not collide with a not-yet-deleted row.
            existing.steps = []
            await self._session.flush()
            existing.steps = _steps_from_config(config)
            await self._session.flush()
            await self._session.refresh(existing)
            return existing

        pipeline = Pipeline(name=config.name, status="active")
        self._apply_header(pipeline, config)
        pipeline.steps = _steps_from_config(config)
        self._session.add(pipeline)
        await self._session.flush()
        await self._session.refresh(pipeline)
        return pipeline

    async def get_by_name(self, name: str) -> Pipeline | None:
        stmt = (
            select(Pipeline)
            .where(Pipeline.name == name)
            .options(selectinload(Pipeline.steps))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        stmt = select(Pipeline).options(selectinload(Pipeline.steps))
        if status is not None:
            stmt = stmt.where(Pipeline.status == status)
        return await self._paginate(stmt, limit=limit, cursor=cursor)

    async def list_all(self) -> list[Pipeline]:
        """Return every pipeline (steps eager-loaded), ordered by name.

        Unpaginated on purpose: the pipeline catalogue is small and callers
        (e.g. ``GET /pipelines``) expect the complete set, not a capped page.
        """
        stmt = (
            select(Pipeline)
            .options(selectinload(Pipeline.steps))
            .order_by(Pipeline.name)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_names(self) -> list[str]:
        result = await self._session.execute(select(Pipeline.name))
        return list(result.scalars().all())

    async def delete_by_name(self, name: str) -> bool:
        pipeline = await self.get_by_name(name)
        if pipeline is None:
            return False
        await self._session.delete(pipeline)
        await self._session.flush()
        return True
