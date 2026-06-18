"""Tests for idempotent API key resolution during ``init`` re-runs (B-078)."""

from __future__ import annotations

import pathlib

import pytest

from intellisource.cli.commands.doctor import _API_KEY_PLACEHOLDER
from intellisource.cli.commands.init import _resolve_api_key

_REAL_KEY = "abc123def456abc123def456abc123def456abc123def456abc123def456abc1"


class TestResolveApiKeyInteractiveLeaveBlank:
    """AC1 + AC2: interactive, user leaves blank, .env has a real key -> reuse."""

    def test_reuses_existing_env_key_when_blank(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            f"IS_API_KEY={_REAL_KEY}\nIS_DB_PASSWORD=somepass\n", encoding="utf-8"
        )

        monkeypatch.delenv("IS_API_KEY", raising=False)
        monkeypatch.setattr(
            "intellisource.cli.commands.init.typer.prompt",
            lambda *a, **k: "",
        )

        result = _resolve_api_key(env_file, non_interactive=False)

        assert result == _REAL_KEY

    def test_prints_reuse_message_when_blank(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(f"IS_API_KEY={_REAL_KEY}\n", encoding="utf-8")

        monkeypatch.delenv("IS_API_KEY", raising=False)
        monkeypatch.setattr(
            "intellisource.cli.commands.init.typer.prompt",
            lambda *a, **k: "",
        )

        _resolve_api_key(env_file, non_interactive=False)

        captured = capsys.readouterr()
        assert "IS_API_KEY" in captured.out
        assert "Reusing" in captured.out or "沿用" in captured.out
        # The reuse message must never echo the key value itself.
        assert _REAL_KEY not in captured.out


class TestResolveApiKeyNewEnvironment:
    """AC3: no .env or no IS_API_KEY -> generate new key."""

    def test_generates_new_key_when_no_env_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        # env_file does not exist

        monkeypatch.delenv("IS_API_KEY", raising=False)
        monkeypatch.setattr(
            "intellisource.cli.commands.init.typer.prompt",
            lambda *a, **k: "",
        )

        result = _resolve_api_key(env_file, non_interactive=False)

        assert result  # non-empty
        assert result != _REAL_KEY  # not the pre-existing key

    def test_prints_generated_message_when_no_env_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        env_file = tmp_path / ".env"

        monkeypatch.delenv("IS_API_KEY", raising=False)
        monkeypatch.setattr(
            "intellisource.cli.commands.init.typer.prompt",
            lambda *a, **k: "",
        )

        result = _resolve_api_key(env_file, non_interactive=False)

        captured = capsys.readouterr()
        assert "Generated" in captured.out
        assert result in captured.out

    def test_generates_new_key_when_env_file_has_no_api_key(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("IS_DB_PASSWORD=somepass\n", encoding="utf-8")

        monkeypatch.delenv("IS_API_KEY", raising=False)
        monkeypatch.setattr(
            "intellisource.cli.commands.init.typer.prompt",
            lambda *a, **k: "",
        )

        result = _resolve_api_key(env_file, non_interactive=False)

        assert result
        captured = capsys.readouterr()
        assert "Generated" in captured.out


class TestResolveApiKeyExplicitInput:
    """AC4: user explicitly provides a key -> use that key."""

    def test_uses_explicit_user_input(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(f"IS_API_KEY={_REAL_KEY}\n", encoding="utf-8")

        user_key = "user-provided-key-xyz789"
        monkeypatch.delenv("IS_API_KEY", raising=False)
        monkeypatch.setattr(
            "intellisource.cli.commands.init.typer.prompt",
            lambda *a, **k: user_key,
        )

        result = _resolve_api_key(env_file, non_interactive=False)

        assert result == user_key

    def test_explicit_input_overrides_existing_env(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(f"IS_API_KEY={_REAL_KEY}\n", encoding="utf-8")

        new_key = "brand-new-key-for-override"
        monkeypatch.delenv("IS_API_KEY", raising=False)
        monkeypatch.setattr(
            "intellisource.cli.commands.init.typer.prompt",
            lambda *a, **k: new_key,
        )

        result = _resolve_api_key(env_file, non_interactive=False)

        assert result == new_key
        assert result != _REAL_KEY


class TestResolveApiKeyNonInteractive:
    """AC5 + AC6: non-interactive priority: os.environ > .env existing > generate."""

    def test_ac5_reuses_env_file_key_when_no_environ(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(f"IS_API_KEY={_REAL_KEY}\nOTHER=val\n", encoding="utf-8")

        monkeypatch.delenv("IS_API_KEY", raising=False)

        result = _resolve_api_key(env_file, non_interactive=True)

        assert result == _REAL_KEY

    def test_ac6_os_environ_takes_priority_over_env_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(f"IS_API_KEY={_REAL_KEY}\n", encoding="utf-8")

        environ_key = "environ-key-takes-priority-000"
        monkeypatch.setenv("IS_API_KEY", environ_key)

        result = _resolve_api_key(env_file, non_interactive=True)

        assert result == environ_key
        assert result != _REAL_KEY

    def test_non_interactive_generates_when_no_key_anywhere(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        # no env file, no environ

        monkeypatch.delenv("IS_API_KEY", raising=False)

        result = _resolve_api_key(env_file, non_interactive=True)

        assert result  # non-empty
        assert len(result) == 64  # secrets.token_hex(32) produces 64 hex chars


class TestResolveApiKeyPlaceholderRejected:
    """R-001: the .env.example placeholder is treated as absent, never reused."""

    def test_interactive_blank_generates_new_when_env_has_placeholder(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(f"IS_API_KEY={_API_KEY_PLACEHOLDER}\n", encoding="utf-8")

        monkeypatch.delenv("IS_API_KEY", raising=False)
        monkeypatch.setattr(
            "intellisource.cli.commands.init.typer.prompt",
            lambda *a, **k: "",
        )

        result = _resolve_api_key(env_file, non_interactive=False)

        assert result != _API_KEY_PLACEHOLDER
        assert len(result) == 64

    def test_non_interactive_generates_new_when_env_has_placeholder(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(f"IS_API_KEY={_API_KEY_PLACEHOLDER}\n", encoding="utf-8")

        monkeypatch.delenv("IS_API_KEY", raising=False)

        result = _resolve_api_key(env_file, non_interactive=True)

        assert result != _API_KEY_PLACEHOLDER
        assert len(result) == 64

    def test_non_interactive_ignores_placeholder_in_environ(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(f"IS_API_KEY={_REAL_KEY}\n", encoding="utf-8")

        monkeypatch.setenv("IS_API_KEY", _API_KEY_PLACEHOLDER)

        result = _resolve_api_key(env_file, non_interactive=True)

        # environ placeholder is ignored; falls through to the real .env key
        assert result == _REAL_KEY


class TestResolveApiKeyWhitespaceInput:
    """R-002: whitespace-only interactive input is treated as blank."""

    def test_whitespace_input_falls_through_to_reuse(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(f"IS_API_KEY={_REAL_KEY}\n", encoding="utf-8")

        monkeypatch.delenv("IS_API_KEY", raising=False)
        monkeypatch.setattr(
            "intellisource.cli.commands.init.typer.prompt",
            lambda *a, **k: "   ",
        )

        result = _resolve_api_key(env_file, non_interactive=False)

        assert result == _REAL_KEY
