"""Tests for the project-root / env-file anchoring helpers."""

from __future__ import annotations

import pathlib

import pytest

from intellisource.core import paths


def test_project_root_contains_pyproject() -> None:
    assert (paths.project_root() / "pyproject.toml").is_file()


def test_project_root_is_repo_root_not_src() -> None:
    # Regression guard: the anchor must be the repo root, not .../src.
    root = paths.project_root()
    assert root.name != "src"
    assert (root / "src" / "intellisource").is_dir()


def test_project_root_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setenv("IS_PROJECT_ROOT", str(tmp_path))
    assert paths.project_root() == tmp_path.resolve()


def test_resolve_env_file_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IS_ENV_FILE", raising=False)
    assert paths.resolve_env_file() == paths.project_root() / "docker" / ".env"


def test_resolve_env_file_explicit_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    custom = tmp_path / "custom.env"
    monkeypatch.setenv("IS_ENV_FILE", str(custom))
    assert paths.resolve_env_file() == custom
