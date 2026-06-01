"""Tests for core.settings — provider-key re-export into os.environ."""

from __future__ import annotations

import os
import pathlib

import pytest

from intellisource.core import settings


@pytest.fixture(autouse=True)
def _restore_provider_env() -> object:
    """Snapshot/restore provider keys so setdefault writes don't leak."""
    saved = {k: os.environ.get(k) for k in settings.PROVIDER_ENV_KEYS}
    yield None
    for key, val in saved.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


def _write_env(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    env = tmp_path / ".env"
    env.write_text(body, encoding="utf-8")
    return env


def test_load_provider_env_sets_missing_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env = _write_env(tmp_path, "DEEPSEEK_API_KEY=sk-from-file\n")
    monkeypatch.setattr("intellisource.core.settings.resolve_env_file", lambda: env)

    settings.load_provider_env()

    assert os.environ["DEEPSEEK_API_KEY"] == "sk-from-file"


def test_load_provider_env_does_not_override_existing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real-environ")
    env = _write_env(tmp_path, "DEEPSEEK_API_KEY=sk-from-file\n")
    monkeypatch.setattr("intellisource.core.settings.resolve_env_file", lambda: env)

    settings.load_provider_env()

    assert os.environ["DEEPSEEK_API_KEY"] == "sk-real-environ"


def test_load_provider_env_noop_when_resolver_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # conftest's _isolate_env_file already stubs resolve_env_file -> None.
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    settings.load_provider_env()

    assert "DEEPSEEK_API_KEY" not in os.environ


def test_load_provider_env_noop_when_file_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "intellisource.core.settings.resolve_env_file",
        lambda: tmp_path / "nonexistent.env",
    )

    settings.load_provider_env()

    assert "OPENAI_API_KEY" not in os.environ
