"""Unit tests for stack CLI: GIT_SHA injection, --rebuild flag, _git_sha helper."""

from __future__ import annotations

from subprocess import CompletedProcess
from typing import Any
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
# _git_sha helper
# ---------------------------------------------------------------------------


class TestGitSha:
    """_git_sha returns stripped sha on success, 'unknown' on any failure."""

    def test_success_returns_stripped_sha(self) -> None:
        from intellisource.cli.commands.stack import _git_sha

        with patch("intellisource.cli.commands.stack.subprocess") as mock_sub:
            mock_sub.run.return_value = CompletedProcess(
                args=[], returncode=0, stdout="deadbeef\n", stderr=""
            )
            assert _git_sha() == "deadbeef"

    def test_nonzero_returncode_returns_unknown(self) -> None:
        from intellisource.cli.commands.stack import _git_sha

        with patch("intellisource.cli.commands.stack.subprocess") as mock_sub:
            mock_sub.run.return_value = CompletedProcess(
                args=[], returncode=128, stdout="", stderr="not a git repo"
            )
            assert _git_sha() == "unknown"

    def test_file_not_found_returns_unknown(self) -> None:
        from intellisource.cli.commands.stack import _git_sha

        with patch("intellisource.cli.commands.stack.subprocess") as mock_sub:
            mock_sub.run.side_effect = FileNotFoundError("git not found")
            assert _git_sha() == "unknown"


# ---------------------------------------------------------------------------
# up (normal path): --build + GIT_SHA injected
# ---------------------------------------------------------------------------


class TestUpNormal:
    """up() without --rebuild: single compose up -d --wait --build with GIT_SHA env."""

    @patch("intellisource.cli.commands.stack._preflight_up")
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    @patch("intellisource.cli.commands.stack.subprocess")
    def test_up_argv_contains_up_flags(
        self,
        mock_subprocess: MagicMock,
        _mock_sha: MagicMock,
        _mock_preflight: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, ["up"])

        assert result.exit_code == 0, result.output
        assert mock_subprocess.run.call_count == 1
        argv: list[str] = mock_subprocess.run.call_args[0][0]
        assert "up" in argv
        assert "-d" in argv
        assert "--wait" in argv
        assert "--build" in argv

    @patch("intellisource.cli.commands.stack._preflight_up")
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    @patch("intellisource.cli.commands.stack.subprocess")
    def test_up_env_contains_git_sha(
        self,
        mock_subprocess: MagicMock,
        _mock_sha: MagicMock,
        _mock_preflight: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, ["up"])

        assert result.exit_code == 0, result.output
        passed_env: dict[str, Any] = mock_subprocess.run.call_args.kwargs["env"]
        assert passed_env["GIT_SHA"] == "abc1234"

    @patch("intellisource.cli.commands.stack._preflight_up")
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    @patch("intellisource.cli.commands.stack.subprocess")
    def test_up_shell_false(
        self,
        mock_subprocess: MagicMock,
        _mock_sha: MagicMock,
        _mock_preflight: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        runner.invoke(app, ["up"])

        assert mock_subprocess.run.call_args.kwargs.get("shell", False) is False


# ---------------------------------------------------------------------------
# up --rebuild: build --no-cache first, then up (no --build)
# ---------------------------------------------------------------------------


class TestUpRebuild:
    """up --rebuild: two compose calls in order — build --no-cache, then up."""

    @patch("intellisource.cli.commands.stack._preflight_up")
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    @patch("intellisource.cli.commands.stack.subprocess")
    def test_rebuild_calls_build_then_up_in_order(
        self,
        mock_subprocess: MagicMock,
        _mock_sha: MagicMock,
        _mock_preflight: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, ["up", "--rebuild"])

        assert result.exit_code == 0, result.output
        assert mock_subprocess.run.call_count == 2

        first_call: list[str] = mock_subprocess.run.call_args_list[0][0][0]
        second_call: list[str] = mock_subprocess.run.call_args_list[1][0][0]

        # first call must be compose build --no-cache
        assert "build" in first_call
        assert "--no-cache" in first_call
        assert "up" not in first_call

        # second call must be compose up (no --build flag)
        assert "up" in second_call
        assert "-d" in second_call
        assert "--wait" in second_call
        assert "--build" not in second_call

    @patch("intellisource.cli.commands.stack._preflight_up")
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    @patch("intellisource.cli.commands.stack.subprocess")
    def test_rebuild_both_calls_carry_git_sha(
        self,
        mock_subprocess: MagicMock,
        _mock_sha: MagicMock,
        _mock_preflight: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, ["up", "--rebuild"])

        assert result.exit_code == 0, result.output
        for c in mock_subprocess.run.call_args_list:
            assert c.kwargs["env"]["GIT_SHA"] == "abc1234"

    @patch("intellisource.cli.commands.stack._preflight_up")
    @patch("intellisource.cli.commands.stack._git_sha", return_value="abc1234")
    @patch("intellisource.cli.commands.stack.subprocess")
    def test_rebuild_short_flag(
        self,
        mock_subprocess: MagicMock,
        _mock_sha: MagicMock,
        _mock_preflight: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, ["up", "-r"])

        assert result.exit_code == 0, result.output
        assert mock_subprocess.run.call_count == 2
