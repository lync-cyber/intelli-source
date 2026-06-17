"""Unit tests for up() cold-start preflight checks (AC-1 ~ AC-4)."""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

try:
    from intellisource.cli.main import app
except ImportError as _err:
    pytest.fail(f"Failed to import intellisource.cli.main.app: {_err}")

from typer.testing import CliRunner


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# _weak_credential_vars — pure-function unit tests (AC-3 branch)
# ---------------------------------------------------------------------------


class TestWeakCredentialVars:
    """_weak_credential_vars identifies placeholder credentials in .env."""

    def test_placeholder_env_returns_weak_vars(self, tmp_path: pathlib.Path) -> None:
        from intellisource.cli.commands.stack import _weak_credential_vars

        env_file = tmp_path / ".env"
        env_file.write_text(
            "IS_DB_PASSWORD=change-me-strong-db-password\n"
            "IS_REDIS_PASSWORD=change-me-strong-redis-password\n"
            "IS_API_KEY=change-me-in-production\n"
        )
        result = _weak_credential_vars(env_file)
        assert "IS_DB_PASSWORD" in result
        assert "IS_REDIS_PASSWORD" in result

    def test_strong_password_env_returns_empty(self, tmp_path: pathlib.Path) -> None:
        from intellisource.cli.commands.stack import _weak_credential_vars

        env_file = tmp_path / ".env"
        env_file.write_text(
            "IS_DB_PASSWORD=X7kQ9mR2pL4nV8sT\n"
            "IS_REDIS_PASSWORD=A3bC5dE7fG9hI0jK\n"
            "IS_API_KEY=sk-real-key-1234567890abcdef\n"
        )
        result = _weak_credential_vars(env_file)
        assert result == []

    def test_case_insensitive_detection(self, tmp_path: pathlib.Path) -> None:
        from intellisource.cli.commands.stack import _weak_credential_vars

        env_file = tmp_path / ".env"
        env_file.write_text("IS_DB_PASSWORD=CHANGE-ME-UPPER\n")
        result = _weak_credential_vars(env_file)
        assert "IS_DB_PASSWORD" in result


# ---------------------------------------------------------------------------
# AC-1: .env missing → friendly error, no compose call
# ---------------------------------------------------------------------------


class TestPreflightEnvMissing:
    """up() exits non-zero with init suggestion when docker/.env is absent."""

    @patch("intellisource.cli.commands.stack._run_compose")
    @patch("intellisource.cli.commands.stack._docker_daemon_running", return_value=True)
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    def test_exits_nonzero_when_env_missing(
        self,
        _mock_sha: MagicMock,
        _mock_daemon: MagicMock,
        mock_compose: MagicMock,
        runner: CliRunner,
        tmp_path: pathlib.Path,
    ) -> None:
        missing_path = tmp_path / "nonexistent" / ".env"
        with patch(
            "intellisource.cli.commands.stack._env_path", return_value=missing_path
        ):
            result = runner.invoke(app, ["up"])

        assert result.exit_code != 0
        mock_compose.assert_not_called()

    @patch("intellisource.cli.commands.stack._run_compose")
    @patch("intellisource.cli.commands.stack._docker_daemon_running", return_value=True)
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    def test_output_mentions_init_when_env_missing(
        self,
        _mock_sha: MagicMock,
        _mock_daemon: MagicMock,
        mock_compose: MagicMock,
        runner: CliRunner,
        tmp_path: pathlib.Path,
    ) -> None:
        missing_path = tmp_path / "nonexistent" / ".env"
        with patch(
            "intellisource.cli.commands.stack._env_path", return_value=missing_path
        ):
            result = runner.invoke(app, ["up"])

        assert "init" in result.output.lower()


# ---------------------------------------------------------------------------
# AC-2: Docker daemon not running → friendly error, no compose call
# ---------------------------------------------------------------------------


class TestPreflightDaemonNotRunning:
    """up() exits non-zero with Docker start suggestion when daemon is down."""

    @patch("intellisource.cli.commands.stack._run_compose")
    @patch(
        "intellisource.cli.commands.stack._docker_daemon_running", return_value=False
    )
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    def test_exits_nonzero_when_daemon_down(
        self,
        _mock_sha: MagicMock,
        _mock_daemon: MagicMock,
        mock_compose: MagicMock,
        runner: CliRunner,
        tmp_path: pathlib.Path,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "IS_DB_PASSWORD=X7kQ9mR2pL4nV8sT\nIS_REDIS_PASSWORD=A3bC5dE7fG9hI0jK\n"
        )
        with patch("intellisource.cli.commands.stack._env_path", return_value=env_file):
            result = runner.invoke(app, ["up"])

        assert result.exit_code != 0
        mock_compose.assert_not_called()

    @patch("intellisource.cli.commands.stack._run_compose")
    @patch(
        "intellisource.cli.commands.stack._docker_daemon_running", return_value=False
    )
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    def test_output_mentions_docker_when_daemon_down(
        self,
        _mock_sha: MagicMock,
        _mock_daemon: MagicMock,
        mock_compose: MagicMock,
        runner: CliRunner,
        tmp_path: pathlib.Path,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "IS_DB_PASSWORD=X7kQ9mR2pL4nV8sT\nIS_REDIS_PASSWORD=A3bC5dE7fG9hI0jK\n"
        )
        with patch("intellisource.cli.commands.stack._env_path", return_value=env_file):
            result = runner.invoke(app, ["up"])

        output_lower = result.output.lower()
        assert "docker" in output_lower


# ---------------------------------------------------------------------------
# AC-3: Weak credentials → blocked before compose, lists weak vars
# ---------------------------------------------------------------------------


class TestPreflightWeakCredentials:
    """up() exits non-zero listing weak vars when placeholder passwords detected."""

    @patch("intellisource.cli.commands.stack._run_compose")
    @patch("intellisource.cli.commands.stack._docker_daemon_running", return_value=True)
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    def test_exits_nonzero_with_weak_credentials(
        self,
        _mock_sha: MagicMock,
        _mock_daemon: MagicMock,
        mock_compose: MagicMock,
        runner: CliRunner,
        tmp_path: pathlib.Path,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "IS_DB_PASSWORD=change-me-strong-db-password\n"
            "IS_REDIS_PASSWORD=change-me-strong-redis-password\n"
        )
        with patch("intellisource.cli.commands.stack._env_path", return_value=env_file):
            result = runner.invoke(app, ["up"])

        assert result.exit_code != 0
        mock_compose.assert_not_called()

    @patch("intellisource.cli.commands.stack._run_compose")
    @patch("intellisource.cli.commands.stack._docker_daemon_running", return_value=True)
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    def test_output_lists_weak_var_names(
        self,
        _mock_sha: MagicMock,
        _mock_daemon: MagicMock,
        mock_compose: MagicMock,
        runner: CliRunner,
        tmp_path: pathlib.Path,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "IS_DB_PASSWORD=change-me-strong-db-password\n"
            "IS_REDIS_PASSWORD=change-me-strong-redis-password\n"
        )
        with patch("intellisource.cli.commands.stack._env_path", return_value=env_file):
            result = runner.invoke(app, ["up"])

        assert "IS_DB_PASSWORD" in result.output or "IS_REDIS_PASSWORD" in result.output

    @patch("intellisource.cli.commands.stack._run_compose")
    @patch("intellisource.cli.commands.stack._docker_daemon_running", return_value=True)
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    def test_output_mentions_init_with_weak_credentials(
        self,
        _mock_sha: MagicMock,
        _mock_daemon: MagicMock,
        mock_compose: MagicMock,
        runner: CliRunner,
        tmp_path: pathlib.Path,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("IS_DB_PASSWORD=change-me-strong-db-password\n")
        with patch("intellisource.cli.commands.stack._env_path", return_value=env_file):
            result = runner.invoke(app, ["up"])

        assert "init" in result.output.lower()


# ---------------------------------------------------------------------------
# AC-4: All preflight checks pass → embedding hint printed, compose called
# ---------------------------------------------------------------------------


class TestPreflightAllPass:
    """up() prints embedding wait hint and calls _run_compose when preflight passes."""

    @patch("intellisource.cli.commands.stack._run_compose")
    @patch("intellisource.cli.commands.stack._docker_daemon_running", return_value=True)
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    def test_run_compose_called_when_preflight_passes(
        self,
        _mock_sha: MagicMock,
        _mock_daemon: MagicMock,
        mock_compose: MagicMock,
        runner: CliRunner,
        tmp_path: pathlib.Path,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "IS_DB_PASSWORD=X7kQ9mR2pL4nV8sT\nIS_REDIS_PASSWORD=A3bC5dE7fG9hI0jK\n"
        )
        with patch("intellisource.cli.commands.stack._env_path", return_value=env_file):
            result = runner.invoke(app, ["up"])

        assert result.exit_code == 0, result.output
        mock_compose.assert_called()

    @patch("intellisource.cli.commands.stack._run_compose")
    @patch("intellisource.cli.commands.stack._docker_daemon_running", return_value=True)
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    def test_output_mentions_embedding_hint(
        self,
        _mock_sha: MagicMock,
        _mock_daemon: MagicMock,
        mock_compose: MagicMock,
        runner: CliRunner,
        tmp_path: pathlib.Path,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "IS_DB_PASSWORD=X7kQ9mR2pL4nV8sT\nIS_REDIS_PASSWORD=A3bC5dE7fG9hI0jK\n"
        )
        with patch("intellisource.cli.commands.stack._env_path", return_value=env_file):
            result = runner.invoke(app, ["up"])

        output_lower = result.output.lower()
        assert "embedding" in output_lower
        assert "minut" in output_lower or "minute" in output_lower

    @patch("intellisource.cli.commands.stack._run_compose")
    @patch("intellisource.cli.commands.stack._docker_daemon_running", return_value=True)
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    def test_exits_zero_when_preflight_passes(
        self,
        _mock_sha: MagicMock,
        _mock_daemon: MagicMock,
        mock_compose: MagicMock,
        runner: CliRunner,
        tmp_path: pathlib.Path,
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "IS_DB_PASSWORD=X7kQ9mR2pL4nV8sT\nIS_REDIS_PASSWORD=A3bC5dE7fG9hI0jK\n"
        )
        with patch("intellisource.cli.commands.stack._env_path", return_value=env_file):
            result = runner.invoke(app, ["up"])

        assert result.exit_code == 0
