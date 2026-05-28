"""T-094 AC-5: ConfigWatcher hot-reload integration.

Verifies that when on_config_change is invoked with a newly written YAML
file path, the configured sources are loaded → validated → upserted via
SourceRepository.upsert(). The watchfiles event loop itself is tested in
the unit suite; this integration test targets the end-to-end on-event
handler that bridges ConfigLoader → ConfigValidator → SourceRepository.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource import main as main_mod
from intellisource.config.models import SourceConfig


def _make_yaml(tmp_path: Path) -> Path:
    yaml_file = tmp_path / "sources.yaml"
    yaml_file.write_text(
        "sources:\n"
        "  - name: s8r-hotreload-test\n"
        "    type: rss\n"
        "    url: https://example.com/feed.xml\n"
        "    schedule_interval: 600\n"
    )
    return yaml_file


class TestConfigHotReload:
    """AC-5: on_config_change → SourceRepository.upsert() end-to-end."""

    @pytest.mark.asyncio
    async def test_on_config_change_invokes_source_repository_upsert(
        self, tmp_path: Path
    ) -> None:
        yaml_file = _make_yaml(tmp_path)

        mock_repo = MagicMock()
        mock_repo.upsert = AsyncMock(return_value=None)
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_db = MagicMock()
        mock_db.get_session = MagicMock(return_value=mock_session)

        with (
            patch.object(main_mod, "_db_manager", mock_db),
            patch(
                "intellisource.main.SourceRepository", return_value=mock_repo
            ) as repo_cls,
        ):
            await main_mod.on_config_change(str(yaml_file))

        repo_cls.assert_called_once_with(mock_session)
        mock_repo.upsert.assert_awaited_once()
        upserted: SourceConfig = mock_repo.upsert.await_args.args[0]
        assert upserted.name == "s8r-hotreload-test"
        assert upserted.type == "rss"
        assert upserted.url == "https://example.com/feed.xml"

    @pytest.mark.asyncio
    async def test_on_config_change_skips_when_db_not_initialised(
        self, tmp_path: Path
    ) -> None:
        yaml_file = _make_yaml(tmp_path)

        with (
            patch.object(main_mod, "_db_manager", None),
            patch("intellisource.main.SourceRepository") as repo_cls,
        ):
            await main_mod.on_config_change(str(yaml_file))

        repo_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_config_change_records_version_after_upsert(
        self, tmp_path: Path
    ) -> None:
        """T-099 AC-6: ConfigVersionManager.record_version is invoked."""
        from intellisource.config.loader import ConfigVersionManager
        from intellisource.config.models import SourceConfig

        yaml_file = _make_yaml(tmp_path)

        mock_repo = MagicMock()
        mock_repo.upsert = AsyncMock(return_value=None)
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_db = MagicMock()
        mock_db.get_session = MagicMock(return_value=mock_session)

        version_manager = ConfigVersionManager(
            table_name="config_versions", config_cls=SourceConfig
        )

        with (
            patch.object(main_mod, "_db_manager", mock_db),
            patch.object(main_mod, "_config_version_manager", version_manager),
            patch("intellisource.main.SourceRepository", return_value=mock_repo),
        ):
            await main_mod.on_config_change(str(yaml_file))

        assert version_manager.current_version == 1, (
            "record_version must have been invoked after successful upsert"
        )
        latest = version_manager.rollback(1)
        assert latest[0].name == "s8r-hotreload-test"
