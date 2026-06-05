"""PipelineDefinitionService — single business entrypoint for pipeline definitions.

All pipeline-definition reads/writes (API, CLI, agent tools, the worker run
path) route through this service. The database is the system of record;
``config/pipelines/*.yaml`` files are bootstrap seeds imported via
``seed_from_yaml``. The service maps between the persisted
:class:`~intellisource.storage.models.Pipeline` rows and the canonical
:class:`~intellisource.config.pipeline_models.PipelineConfig` value object.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.config.pipeline_models import PipelineConfig, StepSpec
from intellisource.storage.repositories.pipeline import PipelineRepository

if TYPE_CHECKING:
    from intellisource.storage.models import Pipeline

_DEFAULT_PIPELINES_DIR = Path(__file__).resolve().parents[3] / "config" / "pipelines"

# Names that are safe to interpolate into a filesystem path (no traversal).
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def load_pipeline_config(name: str, *, yaml_dir: Path | None = None) -> PipelineConfig:
    """Resolve a fixed/internal pipeline name to its config from a YAML seed file.

    Used by call sites that reference a built-in pipeline by name without a DB
    session (e.g. the instant-search chat path). Managed pipelines created via
    the API are resolved DB-first through :class:`PipelineDefinitionService`.

    Rejects path-traversal names so a caller-supplied ``name`` can never escape
    the pipelines directory.
    """
    if not _SAFE_NAME.fullmatch(name):
        raise FileNotFoundError(f"pipeline '{name}' not found")
    base = yaml_dir if yaml_dir is not None else _DEFAULT_PIPELINES_DIR
    return PipelineConfig.from_yaml(str(base / f"{name}.yaml"))


class PipelineDefinitionService:
    """Business-logic facade over :class:`PipelineRepository`."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        yaml_dir: Path | None = None,
    ) -> None:
        self._session = session
        self._repo = PipelineRepository(session)
        self._yaml_dir = yaml_dir if yaml_dir is not None else _DEFAULT_PIPELINES_DIR

    def to_config(self, orm: Pipeline) -> PipelineConfig:
        """Map a persisted Pipeline row (steps eager-loaded) to a PipelineConfig."""
        return PipelineConfig(
            name=orm.name,
            mode=orm.mode,
            steps=[cast(StepSpec, dict(step.definition)) for step in orm.steps],
            max_steps=orm.max_steps,
            on_failure=orm.on_failure,
            tools_allowed=list(orm.tools_allowed),
            tools_denied=list(orm.tools_denied),
            system_prompt=orm.system_prompt,
            max_tokens_budget=orm.max_tokens_budget,
            agent_mode=orm.agent_mode,
            tool_permissions=dict(orm.tool_permissions),
        )

    async def get(self, name: str) -> PipelineConfig | None:
        orm = await self._repo.get_by_name(name)
        return self.to_config(orm) if orm is not None else None

    async def load(self, name: str) -> PipelineConfig | None:
        """DB-first resolution of a pipeline name to its config (None if absent)."""
        return await self.get(name)

    async def list_summaries(self) -> list[dict[str, Any]]:
        rows = await self._repo.list_all()
        return [
            {
                "name": p.name,
                "mode": p.mode,
                "max_steps": p.max_steps,
                "tools_allowed": list(p.tools_allowed),
            }
            for p in rows
        ]

    async def create(self, config: PipelineConfig) -> PipelineConfig:
        """Upsert a definition (by name) and return the persisted config."""
        await self._repo.upsert(config)
        orm = await self._repo.get_by_name(config.name)
        if orm is None:  # pragma: no cover - a row written above must exist
            raise RuntimeError(f"pipeline {config.name!r} missing after upsert")
        return self.to_config(orm)

    async def update(self, name: str, fields: dict[str, Any]) -> PipelineConfig | None:
        """Partial-update the named definition; ``None`` if it does not exist.

        Loads the current config, overlays *fields* (``name`` is immutable — the
        path key wins), re-validates via :meth:`PipelineConfig.from_dict`, and
        upserts. A validation error propagates as ``ValueError``.
        """
        existing = await self.get(name)
        if existing is None:
            return None
        merged: dict[str, Any] = {
            "name": existing.name,
            "mode": existing.mode,
            "steps": existing.steps,
            "max_steps": existing.max_steps,
            "on_failure": existing.on_failure,
            "tools_allowed": existing.tools_allowed,
            "tools_denied": existing.tools_denied,
            "system_prompt": existing.system_prompt,
            "max_tokens_budget": existing.max_tokens_budget,
            "agent_mode": existing.agent_mode,
            "tool_permissions": existing.tool_permissions,
        }
        merged.update(fields)
        merged["name"] = name
        return await self.create(PipelineConfig.from_dict(merged))

    async def delete(self, name: str) -> bool:
        return await self._repo.delete_by_name(name)

    async def seed_from_yaml(self) -> int:
        """Import yaml seeds for names not yet in the DB; returns count created.

        Idempotent and non-destructive: a name already present in the database
        is skipped, so DB edits are never clobbered by a later seed pass.
        """
        if not self._yaml_dir.is_dir():
            return 0
        existing = set(await self._repo.list_names())
        created = 0
        for path in sorted(self._yaml_dir.glob("*.yaml")):
            config = PipelineConfig.from_yaml(str(path))
            if config.name in existing:
                continue
            await self._repo.upsert(config)
            existing.add(config.name)
            created += 1
        return created
