"""Tests for `intellisource content backfill-embeddings` CLI (T-BF-2 AC-4/5)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

# ---------------------------------------------------------------------------
# Import CLI app under test — fail-fast with clear message when not implemented
# ---------------------------------------------------------------------------

try:
    from intellisource.cli.main import app
except ImportError as _main_import_err:
    pytest.fail(
        f"Failed to import intellisource.cli.main.app: {_main_import_err}. "
        "Cannot run CLI tests."
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(*, status_code: int = 200, json_data: Any = None) -> MagicMock:
    """Return a MagicMock that mimics an httpx.Response for CLI tests."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = json.dumps(json_data) if json_data is not None else ""
    return resp


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


ACCEPTED_RESPONSE = {"status": "accepted", "task_id": "test-uuid-1234"}


# ---------------------------------------------------------------------------
# AC-4 [生产路径 AC]: content_app is mounted on the CLI app as "content"
# ---------------------------------------------------------------------------


class TestContentCommandRegistered:
    """AC-4: content_app is registered in cli/main.py under name 'content'."""

    def test_content_group_exists_in_cli_app(self, runner: CliRunner) -> None:
        """Running `intellisource content --help` returns exit_code 0."""
        result = runner.invoke(app, ["content", "--help"])
        assert result.exit_code == 0, (
            f"Exit code {result.exit_code} — 'content' command group is not "
            "registered in intellisource.cli.main. "
            "Add: app.add_typer(content.content_app, name='content'). "
            f"Output: {result.stdout}"
        )

    def test_backfill_embeddings_subcommand_in_content_help(
        self, runner: CliRunner
    ) -> None:
        """Running `intellisource content --help` lists 'backfill-embeddings'."""
        result = runner.invoke(app, ["content", "--help"])
        assert result.exit_code == 0, (
            f"'content' command group not registered. Output: {result.stdout}"
        )
        assert "backfill-embeddings" in result.stdout, (
            "'backfill-embeddings' sub-command is not listed in "
            "'content --help' output. "
            "Register via @content_app.command('backfill-embeddings') in "
            "src/intellisource/cli/commands/content.py. "
            f"Output:\n{result.stdout}"
        )

    def test_content_commands_importable_from_content_module(self) -> None:
        """content_app Typer instance is importable from cli.commands.content."""
        try:
            from intellisource.cli.commands import (  # type: ignore[import-untyped]
                content as content_module,
            )
        except ImportError as e:
            pytest.fail(
                f"Cannot import intellisource.cli.commands.content: {e}. "
                "Create src/intellisource/cli/commands/content.py "
                "with content_app = typer.Typer()."
            )
        import typer

        assert isinstance(content_module.content_app, typer.Typer), (
            "content_module.content_app is not a typer.Typer instance, "
            f"got {type(content_module.content_app)}"
        )
        registered_commands = [
            cmd.name for cmd in content_module.content_app.registered_commands
        ]
        assert "backfill-embeddings" in registered_commands, (
            "'backfill-embeddings' not in content_app.registered_commands: "
            f"{registered_commands}. "
            "Use @content_app.command('backfill-embeddings') to register."
        )


# ---------------------------------------------------------------------------
# AC-5: CLI invocation calls _client.post and emits accepted/task_id
# ---------------------------------------------------------------------------


class TestBackfillEmbeddingsCommand:
    """AC-5: `intellisource content backfill-embeddings` POSTs the endpoint
    and emits the accepted response via emit()."""

    @patch("intellisource.cli._client.httpx")
    def test_backfill_command_exits_zero(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        """Command exits with code 0 on a successful 202 response."""
        mock_httpx.post.return_value = _mock_response(
            status_code=202, json_data=ACCEPTED_RESPONSE
        )
        result = runner.invoke(app, ["content", "backfill-embeddings"])
        assert result.exit_code == 0, (
            f"Expected exit code 0, got {result.exit_code}. "
            f"Output: {result.stdout}"
        )

    @patch("intellisource.cli._client.httpx")
    def test_backfill_command_posts_correct_endpoint(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        """Command POSTs to /api/v1/content/backfill-embeddings."""
        mock_httpx.post.return_value = _mock_response(
            status_code=202, json_data=ACCEPTED_RESPONSE
        )
        runner.invoke(app, ["content", "backfill-embeddings"])
        assert mock_httpx.post.call_count == 1, (
            "Expected _client.post to be called once, "
            f"got {mock_httpx.post.call_count}"
        )
        called_url: str = mock_httpx.post.call_args.args[0]
        assert called_url.endswith("/api/v1/content/backfill-embeddings"), (
            "Expected URL ending in '/api/v1/content/backfill-embeddings', "
            f"got {called_url!r}"
        )

    @patch("intellisource.cli._client.httpx")
    def test_backfill_command_stdout_contains_accepted(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        """stdout contains 'accepted' from the API response (via emit)."""
        mock_httpx.post.return_value = _mock_response(
            status_code=202, json_data=ACCEPTED_RESPONSE
        )
        result = runner.invoke(app, ["content", "backfill-embeddings"])
        assert result.exit_code == 0, (
            f"Command failed (exit {result.exit_code}): {result.stdout}"
        )
        assert "accepted" in result.stdout, (
            "Expected 'accepted' in stdout (from emit of API response), "
            f"got: {result.stdout!r}"
        )

    @patch("intellisource.cli._client.httpx")
    def test_backfill_command_stdout_contains_task_id(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        """stdout contains 'task_id' or the task_id value from the API response."""
        mock_httpx.post.return_value = _mock_response(
            status_code=202, json_data=ACCEPTED_RESPONSE
        )
        result = runner.invoke(app, ["content", "backfill-embeddings"])
        assert result.exit_code == 0, (
            f"Command failed (exit {result.exit_code}): {result.stdout}"
        )
        assert "task_id" in result.stdout or "test-uuid-1234" in result.stdout, (
            f"Expected 'task_id' or its value in stdout, got: {result.stdout!r}"
        )

    @patch("intellisource.cli._client.httpx")
    def test_backfill_command_no_local_gateway_dependency(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        """Command works purely as an HTTP client — no LLMGateway calls."""
        mock_httpx.post.return_value = _mock_response(
            status_code=202, json_data=ACCEPTED_RESPONSE
        )
        result = runner.invoke(app, ["content", "backfill-embeddings"])
        assert mock_httpx.post.call_count == 1, (
            "httpx.post was not called — command may be using LLMGateway "
            "directly rather than the HTTP client."
        )
        assert result.exit_code == 0, (
            "Command should succeed via HTTP client mock only (no local gateway). "
            f"Exit {result.exit_code}, output: {result.stdout}"
        )

    @patch("intellisource.cli._client.httpx")
    def test_backfill_command_json_flag_emits_json(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        """With --json flag, stdout is valid JSON containing status and task_id."""
        mock_httpx.post.return_value = _mock_response(
            status_code=202, json_data=ACCEPTED_RESPONSE
        )
        result = runner.invoke(app, ["content", "backfill-embeddings", "--json"])
        assert result.exit_code == 0, (
            "Command failed with --json flag "
            f"(exit {result.exit_code}): {result.stdout}"
        )
        try:
            parsed = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            pytest.fail(
                f"--json flag output is not valid JSON: {result.stdout!r}"
            )
        assert parsed.get("status") == "accepted", (
            f"Parsed JSON missing status=='accepted': {parsed}"
        )
        assert parsed.get("task_id") == "test-uuid-1234", (
            f"Parsed JSON missing task_id=='test-uuid-1234': {parsed}"
        )


# ---------------------------------------------------------------------------
# R-006: Non-2xx response -> non-zero exit + error output (no crash on JSON)
# ---------------------------------------------------------------------------


class TestBackfillCommandErrorHandling:
    """R-006: CLI checks HTTP status; non-2xx exits with code 1 + error output."""

    @patch("intellisource.cli._client.httpx")
    def test_503_exits_nonzero(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        """503 response must cause CLI to exit with non-zero code."""
        mock_httpx.post.return_value = _mock_response(
            status_code=503,
            json_data={"detail": "broker unavailable: connection refused"},
        )
        result = runner.invoke(app, ["content", "backfill-embeddings"])
        assert result.exit_code != 0, (
            f"Expected non-zero exit for 503 response, got {result.exit_code}. "
            "CLI must check resp.status_code >= 400 and raise typer.Exit(1)."
        )

    @patch("intellisource.cli._client.httpx")
    def test_503_outputs_error_message(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        """503 response must cause the error detail to be emitted (exit 1)."""
        mock_httpx.post.return_value = _mock_response(
            status_code=503,
            json_data={"detail": "broker unavailable: connection refused"},
        )
        result = runner.invoke(app, ["content", "backfill-embeddings"])
        assert result.exit_code == 1, (
            f"Expected exit code 1 for 503 response, got {result.exit_code}."
        )
        # CliRunner (click 8.1, mix_stderr=True) folds the err=True echo into
        # result.output; the API error detail must surface so the operator sees
        # why the trigger failed rather than only a bare non-zero exit.
        assert "unavailable" in result.output.lower(), (
            "503 error detail must be emitted to the user, "
            f"got output: {result.output!r}"
        )

    @patch("intellisource.cli._client.httpx")
    def test_400_exits_nonzero(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        """400 response must also cause CLI to exit with non-zero code."""
        mock_httpx.post.return_value = _mock_response(
            status_code=400,
            json_data={"detail": "bad request"},
        )
        result = runner.invoke(app, ["content", "backfill-embeddings"])
        assert result.exit_code != 0, (
            f"Expected non-zero exit for 400 response, got {result.exit_code}."
        )
