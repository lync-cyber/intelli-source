"""Tests for SubscriptionConfigLoader (Phase 1)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from intellisource.config.loader import ConfigPathError
from intellisource.config.subscription_loader import SubscriptionConfigLoader


class TestLoadSubscriptionConfigsScan:
    def test_unset_dir_returns_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("IS_SUBSCRIPTION_CONFIG_DIR", None)
            loader = SubscriptionConfigLoader()
            assert loader.load_subscription_configs() == []

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        ghost = tmp_path / "does-not-exist"
        with patch.dict(os.environ, {"IS_SUBSCRIPTION_CONFIG_DIR": str(ghost)}):
            loader = SubscriptionConfigLoader()
            assert loader.load_subscription_configs() == []

    def test_loads_yaml_files_in_sorted_order(self, tmp_path: Path) -> None:
        (tmp_path / "b.yaml").write_text(
            'subscriptions:\n  - name: "B-sub"\n    channel: "wechat"\n'
            "    channel_config: {}\n    match_rules: {}\n",
            encoding="utf-8",
        )
        (tmp_path / "a.yaml").write_text(
            'subscriptions:\n  - name: "A-sub"\n    channel: "wechat"\n'
            "    channel_config: {}\n    match_rules: {}\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"IS_SUBSCRIPTION_CONFIG_DIR": str(tmp_path)}):
            loader = SubscriptionConfigLoader()
            configs = loader.load_subscription_configs()
        names = [c.name for c in configs]
        assert names == ["A-sub", "B-sub"]

    def test_corrupt_yaml_logs_but_does_not_stop_other_files(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "good.yaml").write_text(
            'subscriptions:\n  - name: "OK"\n    channel: "wechat"\n'
            "    channel_config: {}\n    match_rules: {}\n",
            encoding="utf-8",
        )
        (tmp_path / "broken.yaml").write_text(
            "subscriptions:\n  - name: : broken\n", encoding="utf-8"
        )
        with patch.dict(os.environ, {"IS_SUBSCRIPTION_CONFIG_DIR": str(tmp_path)}):
            loader = SubscriptionConfigLoader()
            configs = loader.load_subscription_configs()
        names = [c.name for c in configs]
        assert names == ["OK"]


class TestLoadFilePathSafety:
    def test_path_outside_config_dir_raises(self, tmp_path: Path) -> None:
        other = tmp_path / "outside"
        other.mkdir()
        outside_file = other / "evil.yaml"
        outside_file.write_text(
            'subscriptions:\n  - name: "evil"\n    channel: "wechat"\n'
            "    channel_config: {}\n    match_rules: {}\n",
            encoding="utf-8",
        )
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        with patch.dict(os.environ, {"IS_SUBSCRIPTION_CONFIG_DIR": str(allowed)}):
            loader = SubscriptionConfigLoader()
            with pytest.raises(ConfigPathError):
                loader.load_file(str(outside_file))

    def test_load_file_unsupported_extension_raises(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("IS_SUBSCRIPTION_CONFIG_DIR", None)
            loader = SubscriptionConfigLoader()
            txt = tmp_path / "data.txt"
            txt.write_text("anything", encoding="utf-8")
            with pytest.raises(ValueError, match="Unsupported file extension"):
                loader.load_file(str(txt))

    def test_load_file_validates_through_validator(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "subs.yaml"
        yaml_file.write_text(
            'subscriptions:\n  - name: ""\n    channel: "wechat"\n'
            "    channel_config: {}\n    match_rules: {}\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"IS_SUBSCRIPTION_CONFIG_DIR": str(tmp_path)}):
            loader = SubscriptionConfigLoader()
            with pytest.raises(ValueError, match="Validation failed"):
                loader.load_file(str(yaml_file))
