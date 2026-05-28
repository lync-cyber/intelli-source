"""Smoke test: build_source_version_manager factory returns a correctly configured
ConfigVersionManager instance targeting the config_versions table.
"""

from __future__ import annotations

from intellisource.config.loader import ConfigVersionManager
from intellisource.config.models import SourceConfig

# Import the not-yet-existing factory (will ImportError → RED)
from intellisource.source.service import (
    build_source_version_manager,  # type: ignore[import]
)


class TestBuildSourceVersionManager:
    def test_factory_returns_config_version_manager_instance(self) -> None:
        manager = build_source_version_manager()
        assert isinstance(manager, ConfigVersionManager), (
            "build_source_version_manager must return a ConfigVersionManager instance; "
            f"got {type(manager)}"
        )

    def test_factory_uses_config_versions_table(self) -> None:
        manager = build_source_version_manager()
        assert manager._table_name == "config_versions", (
            "config_versions_manager must target table_name='config_versions'; "
            f"got '{manager._table_name}'"
        )

    def test_factory_uses_source_config_cls(self) -> None:
        manager = build_source_version_manager()
        assert manager._config_cls is SourceConfig, (
            "config_versions_manager must use config_cls=SourceConfig; "
            f"got {manager._config_cls}"
        )
