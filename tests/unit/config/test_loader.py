"""Tests for T-009: Configuration loading, hot-reload, and version management.

Covers:
  AC-T009-1: ConfigLoader.load_file() parses YAML/JSON and validates via ConfigValidator
  AC-T009-2: ConfigLoader.sync_to_db() syncs configs to Source (create/update/delete)
  AC-T009-3: ConfigWatcher detects file changes and triggers reload callback
  AC-T009-4: Validation failure rejects load; existing configs unaffected
  AC-T009-5: ConfigVersionManager.rollback(version) restores a previous version
  AC-002:    Config changes auto-reload (watchfiles integration)
  AC-004:    Version auto-increment on change; rollback support
"""

from __future__ import annotations

import json

import pytest
import yaml
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from intellisource.config.models import SourceConfig
from intellisource.storage.models import Base, Source

# ---------------------------------------------------------------------------
# Sample config data
# ---------------------------------------------------------------------------

VALID_SOURCE_A = {
    "name": "arxiv-cs",
    "type": "rss",
    "url": "https://arxiv.org/rss/cs",
    "tags": ["ai"],
}

VALID_SOURCE_B = {
    "name": "hackernews",
    "type": "web",
    "url": "https://news.ycombinator.com/rss",
    "tags": ["tech"],
}

INVALID_SOURCE = {
    "name": "bad-source",
    "type": "rss",
    "url": "no-scheme-url",  # invalid: missing ://
    "tags": [],
}

# ---------------------------------------------------------------------------
# Database fixtures (mirrors test_repositories.py pattern)
# ---------------------------------------------------------------------------

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _remove_pg_only_indexes(base):
    for table in base.metadata.tables.values():
        indexes_to_remove = []
        for idx in table.indexes:
            dialect_options = getattr(idx, "dialect_options", {})
            pg_opts = dialect_options.get("postgresql", {})
            if pg_opts.get("using") or pg_opts.get("ops"):
                indexes_to_remove.append(idx)
        for idx in indexes_to_remove:
            table.indexes.discard(idx)


def _set_sqlite_fk_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
async def engine():
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)
    _remove_pg_only_indexes(Base)

    for table in Base.metadata.tables.values():
        for col in table.columns:
            type_name = type(col.type).__name__
            if type_name == "Vector":
                col.type = Text()
            elif type_name == "ARRAY":
                from sqlalchemy import JSON

                col.type = JSON()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def session(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as sess:
        yield sess


# ===========================================================================
# AC-T009-1: ConfigLoader.load_file() parses YAML/JSON and validates
# ===========================================================================


class TestConfigLoaderLoadFile:
    """AC-T009-1: ConfigLoader.load_file() parses YAML/JSON and calls validator."""

    def test_import_config_loader(self) -> None:
        """ConfigLoader class must be importable from config.loader."""
        from intellisource.config.loader import ConfigLoader

        assert ConfigLoader is not None

    def test_load_yaml_file(self, tmp_path) -> None:
        """load_file() parses a YAML config and returns list[SourceConfig]."""
        from intellisource.config.loader import ConfigLoader

        config_file = tmp_path / "sources.yaml"
        config_file.write_text(yaml.dump({"sources": [VALID_SOURCE_A]}))

        loader = ConfigLoader()
        result = loader.load_file(str(config_file))

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], SourceConfig)
        assert result[0].name == "arxiv-cs"

    def test_load_json_file(self, tmp_path) -> None:
        """load_file() parses a JSON config and returns list[SourceConfig]."""
        from intellisource.config.loader import ConfigLoader

        config_file = tmp_path / "sources.json"
        config_file.write_text(
            json.dumps({"sources": [VALID_SOURCE_A, VALID_SOURCE_B]})
        )

        loader = ConfigLoader()
        result = loader.load_file(str(config_file))

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].name == "arxiv-cs"
        assert result[1].name == "hackernews"

    def test_load_file_detects_format_by_extension(self, tmp_path) -> None:
        """load_file() auto-detects yaml vs json from file extension."""
        from intellisource.config.loader import ConfigLoader

        yml_file = tmp_path / "sources.yml"
        yml_file.write_text(yaml.dump({"sources": [VALID_SOURCE_A]}))

        loader = ConfigLoader()
        result = loader.load_file(str(yml_file))

        assert len(result) == 1
        assert result[0].name == "arxiv-cs"


# ===========================================================================
# AC-T009-2: ConfigLoader.sync_to_db() syncs to Source table
# ===========================================================================


class TestConfigLoaderSyncToDb:
    """AC-T009-2: sync_to_db() creates/updates/marks-deleted in Source table."""

    @pytest.mark.asyncio
    async def test_sync_creates_new_sources(self, session: AsyncSession) -> None:
        """sync_to_db() creates Source rows for new configs."""
        from intellisource.config.loader import ConfigLoader

        loader = ConfigLoader()
        configs = [
            SourceConfig(**VALID_SOURCE_A),
            SourceConfig(**VALID_SOURCE_B),
        ]

        await loader.sync_to_db(configs, session)

        from sqlalchemy import select

        result = await session.execute(select(Source))
        sources = result.scalars().all()
        names = {s.name for s in sources}

        assert "arxiv-cs" in names
        assert "hackernews" in names

    @pytest.mark.asyncio
    async def test_sync_updates_existing_source(self, session: AsyncSession) -> None:
        """sync_to_db() updates an existing Source when name matches."""
        from intellisource.config.loader import ConfigLoader

        loader = ConfigLoader()

        # First sync
        configs_v1 = [SourceConfig(**VALID_SOURCE_A)]
        await loader.sync_to_db(configs_v1, session)

        # Modify config and sync again
        updated_data = {**VALID_SOURCE_A, "tags": ["ai", "research"]}
        configs_v2 = [SourceConfig(**updated_data)]
        await loader.sync_to_db(configs_v2, session)

        from sqlalchemy import select

        result = await session.execute(select(Source).where(Source.name == "arxiv-cs"))
        source = result.scalar_one()
        assert "research" in source.tags

    @pytest.mark.asyncio
    async def test_sync_marks_removed_sources(self, session: AsyncSession) -> None:
        """sync_to_db() marks sources as deleted/paused if absent from config."""
        from intellisource.config.loader import ConfigLoader

        loader = ConfigLoader()

        # Sync with two sources
        configs_v1 = [
            SourceConfig(**VALID_SOURCE_A),
            SourceConfig(**VALID_SOURCE_B),
        ]
        await loader.sync_to_db(configs_v1, session)

        # Sync with only one source (B removed)
        configs_v2 = [SourceConfig(**VALID_SOURCE_A)]
        await loader.sync_to_db(configs_v2, session)

        from sqlalchemy import select

        result = await session.execute(
            select(Source).where(Source.name == "hackernews")
        )
        source = result.scalar_one()
        assert source.status in ("deleted", "paused")


# ===========================================================================
# AC-T009-3 / AC-002: ConfigWatcher detects file changes and triggers reload
# ===========================================================================


class TestConfigWatcher:
    """AC-T009-3 / AC-002: ConfigWatcher monitors config dir for changes."""

    def test_import_config_watcher(self) -> None:
        """ConfigWatcher class must be importable."""
        from intellisource.config.loader import ConfigWatcher

        assert ConfigWatcher is not None

    def test_watcher_init_with_callback(self, tmp_path) -> None:
        """ConfigWatcher accepts config_dir and callback."""
        from intellisource.config.loader import ConfigWatcher

        callback = lambda path: None  # noqa: E731
        watcher = ConfigWatcher(config_dir=str(tmp_path), callback=callback)

        assert watcher is not None

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_watcher_triggers_callback_on_file_change(self, tmp_path) -> None:
        """ConfigWatcher calls callback when a config file is modified."""
        from unittest.mock import MagicMock

        from intellisource.config.loader import ConfigWatcher

        callback = MagicMock()
        watcher = ConfigWatcher(config_dir=str(tmp_path), callback=callback)

        # Create a config file to trigger the watcher
        config_file = tmp_path / "sources.yaml"
        config_file.write_text(yaml.dump({"sources": [VALID_SOURCE_A]}))

        # Simulate the watcher detecting the change
        # The watcher should call the callback when a file changes
        await watcher.start()

        # Modify the file
        config_file.write_text(yaml.dump({"sources": [VALID_SOURCE_A, VALID_SOURCE_B]}))

        # Give the watcher a moment to detect changes
        import asyncio

        await asyncio.sleep(0.2)

        await watcher.stop()

        # The callback should have been invoked at least once
        assert callback.call_count >= 1

    def test_watcher_has_start_stop_methods(self, tmp_path) -> None:
        """ConfigWatcher exposes start() and stop() lifecycle methods."""
        from intellisource.config.loader import ConfigWatcher

        callback = lambda path: None  # noqa: E731
        watcher = ConfigWatcher(config_dir=str(tmp_path), callback=callback)

        assert callable(getattr(watcher, "start", None))
        assert callable(getattr(watcher, "stop", None))


# ===========================================================================
# AC-T009-4: Validation failure rejects load; existing config unaffected
# ===========================================================================


class TestValidationFailureRejection:
    """AC-T009-4: When validation fails, load is rejected and existing
    configs remain unaffected."""

    def test_load_file_raises_on_invalid_config(self, tmp_path) -> None:
        """load_file() raises an error when config contains invalid sources."""
        from intellisource.config.loader import ConfigLoader

        config_file = tmp_path / "bad.yaml"
        config_file.write_text(yaml.dump({"sources": [INVALID_SOURCE]}))

        loader = ConfigLoader()

        with pytest.raises((ValueError, Exception)):
            loader.load_file(str(config_file))

    @pytest.mark.asyncio
    async def test_failed_load_does_not_affect_existing(
        self, session: AsyncSession, tmp_path
    ) -> None:
        """If a reload fails validation, previously synced sources remain intact."""
        from intellisource.config.loader import ConfigLoader

        loader = ConfigLoader()

        # Sync valid config first
        configs_v1 = [SourceConfig(**VALID_SOURCE_A)]
        await loader.sync_to_db(configs_v1, session)

        # Try to load invalid config file -- should fail
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text(yaml.dump({"sources": [INVALID_SOURCE]}))

        with pytest.raises((ValueError, Exception)):
            loader.load_file(str(bad_file))

        # Existing source should still be in DB
        from sqlalchemy import select

        result = await session.execute(select(Source).where(Source.name == "arxiv-cs"))
        source = result.scalar_one_or_none()
        assert source is not None
        assert source.status == "active"


# ===========================================================================
# AC-T009-5 / AC-004: ConfigVersionManager with version tracking and rollback
# ===========================================================================


class TestConfigVersionManager:
    """AC-T009-5 / AC-004: ConfigVersionManager tracks versions, supports rollback."""

    def test_import_config_version_manager(self) -> None:
        """ConfigVersionManager class must be importable."""
        from intellisource.config.loader import ConfigVersionManager

        assert ConfigVersionManager is not None

    def test_record_version_increments(self) -> None:
        """record_version() increments the version number."""
        from intellisource.config.loader import ConfigVersionManager

        mgr = ConfigVersionManager(
            table_name="config_versions", config_cls=SourceConfig
        )

        configs_v1 = [SourceConfig(**VALID_SOURCE_A)]
        mgr.record_version(configs_v1)
        v1 = mgr.current_version

        configs_v2 = [SourceConfig(**VALID_SOURCE_A), SourceConfig(**VALID_SOURCE_B)]
        mgr.record_version(configs_v2)
        v2 = mgr.current_version

        assert v2 == v1 + 1

    def test_rollback_to_previous_version(self) -> None:
        """rollback(version) returns the config snapshot at that version."""
        from intellisource.config.loader import ConfigVersionManager

        mgr = ConfigVersionManager(
            table_name="config_versions", config_cls=SourceConfig
        )

        configs_v1 = [SourceConfig(**VALID_SOURCE_A)]
        mgr.record_version(configs_v1)
        v1 = mgr.current_version

        configs_v2 = [SourceConfig(**VALID_SOURCE_A), SourceConfig(**VALID_SOURCE_B)]
        mgr.record_version(configs_v2)

        # Rollback to v1
        restored = mgr.rollback(v1)

        assert isinstance(restored, list)
        assert len(restored) == 1
        assert restored[0].name == "arxiv-cs"  # type: ignore[attr-defined]

    def test_rollback_restores_current_version(self) -> None:
        """After rollback, current_version reflects the rolled-back version."""
        from intellisource.config.loader import ConfigVersionManager

        mgr = ConfigVersionManager(
            table_name="config_versions", config_cls=SourceConfig
        )

        mgr.record_version([SourceConfig(**VALID_SOURCE_A)])
        v1 = mgr.current_version

        mgr.record_version(
            [SourceConfig(**VALID_SOURCE_A), SourceConfig(**VALID_SOURCE_B)]
        )

        mgr.rollback(v1)
        assert mgr.current_version == v1

    def test_current_version_property(self) -> None:
        """current_version is accessible as a property and returns an int."""
        from intellisource.config.loader import ConfigVersionManager

        mgr = ConfigVersionManager(
            table_name="config_versions", config_cls=SourceConfig
        )
        configs = [SourceConfig(**VALID_SOURCE_A)]
        mgr.record_version(configs)

        assert isinstance(mgr.current_version, int)


# ===========================================================================
# Path-traversal guard + load_source_configs scan
# ===========================================================================


class TestConfigLoaderPathGuard:
    """Path-traversal guard in load_file() and directory-scan in load_source_configs."""

    def test_load_file_rejects_path_traversal(self, tmp_path, monkeypatch) -> None:
        """load_file() raises ConfigPathError when path escapes the config dir."""
        from intellisource.config.loader import ConfigLoader, ConfigPathError

        monkeypatch.setenv("IS_SOURCE_CONFIG_DIR", str(tmp_path))
        loader = ConfigLoader()

        outside = str(tmp_path / ".." / "escape.yaml")
        with pytest.raises(ConfigPathError):
            loader.load_file(outside)

    def test_load_file_rejects_absolute_escape(self, tmp_path, monkeypatch) -> None:
        """load_file() raises ConfigPathError for absolute path outside config_dir."""
        from intellisource.config.loader import ConfigLoader, ConfigPathError

        monkeypatch.setenv("IS_SOURCE_CONFIG_DIR", str(tmp_path))
        loader = ConfigLoader()

        outside = "/tmp/should_not_load.yaml"
        with pytest.raises(ConfigPathError):
            loader.load_file(outside)

    def test_load_file_accepts_legitimate_file(self, tmp_path, monkeypatch) -> None:
        """load_file() succeeds for a file inside the configured config_dir."""
        from intellisource.config.loader import ConfigLoader

        monkeypatch.setenv("IS_SOURCE_CONFIG_DIR", str(tmp_path))
        loader = ConfigLoader()

        config_file = tmp_path / "sources.yaml"
        config_file.write_text(yaml.dump({"sources": [VALID_SOURCE_A]}))

        result = loader.load_file(str(config_file))
        assert len(result) == 1
        assert result[0].name == "arxiv-cs"

    def test_load_source_configs_scans_directory(self, tmp_path, monkeypatch) -> None:
        """load_source_configs() returns configs from all YAML files in the dir."""
        from intellisource.config.loader import ConfigLoader

        monkeypatch.setenv("IS_SOURCE_CONFIG_DIR", str(tmp_path))

        (tmp_path / "a.yaml").write_text(yaml.dump({"sources": [VALID_SOURCE_A]}))
        (tmp_path / "b.yaml").write_text(yaml.dump({"sources": [VALID_SOURCE_B]}))

        loader = ConfigLoader()
        result = loader.load_source_configs()

        names = {c.name for c in result}
        assert "arxiv-cs" in names
        assert "hackernews" in names

    def test_load_source_configs_skips_non_yaml(self, tmp_path, monkeypatch) -> None:
        """load_source_configs() ignores non-YAML files in the directory."""
        from intellisource.config.loader import ConfigLoader

        monkeypatch.setenv("IS_SOURCE_CONFIG_DIR", str(tmp_path))

        (tmp_path / "sources.yaml").write_text(yaml.dump({"sources": [VALID_SOURCE_A]}))
        (tmp_path / "readme.txt").write_text("this is not a yaml config")

        loader = ConfigLoader()
        result = loader.load_source_configs()

        assert len(result) == 1
        assert result[0].name == "arxiv-cs"

    def test_load_source_configs_empty_dir_returns_empty_list(
        self, tmp_path, monkeypatch
    ) -> None:
        """load_source_configs() returns [] when the config directory is empty."""
        from intellisource.config.loader import ConfigLoader

        monkeypatch.setenv("IS_SOURCE_CONFIG_DIR", str(tmp_path))
        loader = ConfigLoader()

        result = loader.load_source_configs()
        assert result == []
