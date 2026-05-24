"""Configuration loading, watching, and version management."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.config.models import SourceConfig
from intellisource.config.validator import ConfigValidator
from intellisource.storage.models import Source

logger = logging.getLogger(__name__)


class ConfigPathError(ValueError):
    """Raised when a config file path escapes the allowed config directory."""


_FORMAT_MAP: dict[str, str] = {
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
}


def _detect_format(file_path: str) -> str:
    """Return the config format string based on file extension."""
    for ext, fmt in _FORMAT_MAP.items():
        if file_path.endswith(ext):
            return fmt
    raise ValueError(f"Unsupported file extension: {file_path}")


def _update_source_from_config(source: Source, config: SourceConfig) -> None:
    """Apply configuration values to an existing Source ORM instance."""
    source.type = config.type
    source.url = config.url
    source.tags = config.tags
    source.schedule_interval = config.schedule_interval
    source.schedule_adaptive = config.schedule_adaptive
    source.proxy = config.proxy
    source.rate_limit_qps = config.rate_limit_qps
    source.rate_limit_concurrency = config.rate_limit_concurrency
    source.metadata_ = config.metadata


def _create_source_from_config(config: SourceConfig) -> Source:
    """Create a new Source ORM instance from a SourceConfig."""
    return Source(
        name=config.name,
        type=config.type,
        url=config.url,
        tags=config.tags,
        status="active",
        schedule_interval=config.schedule_interval,
        schedule_adaptive=config.schedule_adaptive,
        proxy=config.proxy,
        rate_limit_qps=config.rate_limit_qps,
        rate_limit_concurrency=config.rate_limit_concurrency,
        metadata_=config.metadata,
    )


class ConfigLoader:
    """Loads configuration files and syncs to database."""

    def __init__(self) -> None:
        self._validator = ConfigValidator()
        config_dir_env = os.environ.get("IS_SOURCE_CONFIG_DIR", "")
        self._config_dir: Path | None = Path(config_dir_env) if config_dir_env else None

    def load_file(self, file_path: str) -> list[SourceConfig]:
        """Load and validate a configuration file (YAML or JSON).

        Raises ConfigPathError if the resolved path escapes the config directory.
        Detects format from file extension and delegates to ConfigValidator.
        """
        resolved = Path(file_path).resolve()

        if self._config_dir is not None:
            allowed_dir = self._config_dir.resolve()
            try:
                resolved.relative_to(allowed_dir)
            except ValueError:
                raise ConfigPathError(
                    f"path {file_path!r} escapes config directory {str(allowed_dir)!r}"
                )

        fmt = _detect_format(file_path)

        with open(resolved, encoding="utf-8") as f:
            content = f.read()

        return self._validator.validate_sources_file(content, format=fmt)

    def load_source_configs(self) -> list[SourceConfig]:
        """Scan the configured directory and load all *.yaml / *.yml config files.

        Returns an empty list when SOURCE_CONFIG_DIR is unset or does not exist.
        """
        if self._config_dir is None:
            logger.warning("IS_SOURCE_CONFIG_DIR is not set; skipping config scan")
            return []

        config_dir = self._config_dir.resolve()
        if not config_dir.is_dir():
            logger.warning(
                "Config directory %s does not exist; skipping config scan", config_dir
            )
            return []

        results: list[SourceConfig] = []
        for pattern in ("*.yaml", "*.yml"):
            for config_path in sorted(config_dir.glob(pattern)):
                try:
                    loaded = self.load_file(str(config_path))
                    results.extend(loaded)
                except Exception:
                    logger.exception("Failed to load config file %s", config_path)

        return results

    async def sync_to_db(
        self, configs: Sequence[SourceConfig], session: AsyncSession
    ) -> None:
        """Sync source configs to the database.

        Creates new sources, updates existing ones, and marks removed ones as paused.
        """
        config_by_name: dict[str, SourceConfig] = {c.name: c for c in configs}

        result = await session.execute(select(Source))
        existing_sources: Sequence[Any] = result.scalars().all()
        existing_by_name: dict[str, Source] = {s.name: s for s in existing_sources}

        for name, config in config_by_name.items():
            if name in existing_by_name:
                _update_source_from_config(existing_by_name[name], config)
            else:
                session.add(_create_source_from_config(config))

        for name, source in existing_by_name.items():
            if name not in config_by_name:
                source.status = "paused"

        await session.flush()


class ConfigWatcher:
    """Watches a directory for configuration file changes."""

    def __init__(
        self,
        config_dir: str,
        callback: Callable[..., Any],
    ) -> None:
        self._config_dir = config_dir
        self._on_change = callback
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start watching for file changes."""
        self._task = asyncio.create_task(self._watch())
        # Yield control to allow the watch task to initialize
        await asyncio.sleep(0.1)

    async def stop(self) -> None:
        """Stop watching for file changes."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _watch(self) -> None:
        """Internal watch loop using watchfiles."""
        import inspect

        from watchfiles import awatch

        try:
            async for changes in awatch(self._config_dir, step=100):
                for _change_type, path in changes:
                    try:
                        result = self._on_change(path)
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        logger.exception("on_change callback failed for %s", path)
        except (FileNotFoundError, OSError):
            logger.warning(
                "Config directory not found or inaccessible: %s", self._config_dir
            )


class ConfigVersionManager:
    """Version tracking and rollback for configurations.

    Maintains an in-memory cache for fast reads; when a session_factory is
    injected, each new version is also written to the config_versions table
    for cross-process durability.
    """

    def __init__(
        self,
        session_factory: Any | None = None,
    ) -> None:
        self._versions: dict[int, list[SourceConfig]] = {}
        self._current_version: int = 0
        self._session_factory = session_factory

    @property
    def current_version(self) -> int:
        """Return the current version number."""
        return self._current_version

    def record_version(self, configs: list[SourceConfig]) -> None:
        """Record a new version snapshot, incrementing the version number."""
        self._current_version += 1
        self._versions[self._current_version] = list(configs)

    async def record_version_async(
        self,
        configs: list[SourceConfig],
        author: str | None = None,
    ) -> str:
        """Record a version snapshot and persist to DB. Returns version label."""
        self._current_version += 1
        self._versions[self._current_version] = list(configs)
        version_label = str(self._current_version)
        if self._session_factory is not None:
            snapshot = yaml.dump([c.model_dump() for c in configs], allow_unicode=True)
            async with self._session_factory() as session:
                await session.execute(
                    text(
                        "INSERT INTO config_versions"
                        " (id, version, snapshot_yaml, author)"
                        " VALUES (:id, :version, :snapshot_yaml, :author)"
                        " ON CONFLICT (version) DO NOTHING"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "version": version_label,
                        "snapshot_yaml": snapshot,
                        "author": author,
                    },
                )
                await session.commit()
        return version_label

    def rollback(self, version: int) -> list[SourceConfig]:
        """Rollback to a specific version and return its config snapshot."""
        if version not in self._versions:
            raise ValueError(f"Version {version} not found")
        self._current_version = version
        return list(self._versions[version])

    async def rollback_by_label(self, version_label: str) -> list[SourceConfig]:
        """Rollback to a version by its string label.

        Checks the in-memory cache first; falls back to DB if a
        session_factory was injected.
        """
        try:
            version_int = int(version_label)
        except ValueError:
            raise ValueError(f"Version '{version_label}' not found")
        if version_int in self._versions:
            self._current_version = version_int
            return list(self._versions[version_int])
        if self._session_factory is not None:
            async with self._session_factory() as session:
                row = await session.execute(
                    text(
                        "SELECT snapshot_yaml FROM config_versions WHERE version = :v"
                    ),
                    {"v": version_label},
                )
                result = row.fetchone()
                if result is None:
                    raise ValueError(f"Version '{version_label}' not found")
                raw = yaml.safe_load(result[0])
                configs = [SourceConfig(**item) for item in raw]
                self._versions[version_int] = configs
                self._current_version = version_int
                return list(configs)
        raise ValueError(f"Version '{version_label}' not found")
