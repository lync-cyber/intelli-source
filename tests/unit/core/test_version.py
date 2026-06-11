"""Tests for the package version resolver."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest

from intellisource.core import version as version_mod
from intellisource.core.version import get_version


def test_get_version_prefers_installed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(version_mod.metadata, "version", lambda *_: "9.9.9")
    assert get_version() == "9.9.9"


def test_get_version_falls_back_to_pyproject(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _missing(_name: str) -> str:
        raise metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(version_mod.metadata, "version", _missing)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    fake_file = tmp_path / "src" / "intellisource" / "core" / "version.py"
    monkeypatch.setattr(version_mod, "__file__", str(fake_file))
    assert get_version() == "1.2.3"


def test_get_version_sentinel_when_no_metadata_and_no_pyproject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing(_name: str) -> str:
        raise metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(version_mod.metadata, "version", _missing)
    monkeypatch.setattr(version_mod, "_version_from_pyproject", lambda: None)
    assert get_version() == "0.0.0+unknown"
