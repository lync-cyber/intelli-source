"""Tests for T-044: CLI tool commands.

Covers:
  AC-T044-1: source list/add/update/delete commands
  AC-T044-2: task trigger/status commands
  AC-T044-3: pipeline list command
  AC-T044-4: search command
  AC-T044-5: table (default) or JSON (--json) output format
  AC-T044-6: API url/key configured via env vars or CLI args
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# The CLI app module does not exist yet -- import may fail during RED phase.
try:
    from intellisource.cli.main import app  # type: ignore[import-untyped]
except ImportError:
    app = None  # type: ignore[assignment]

_MODULE_MISSING = app is None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skip_if_missing() -> None:
    """Fail the test immediately when the module under test is not implemented."""
    if _MODULE_MISSING:
        pytest.fail("intellisource.cli.main not implemented")


def _mock_response(
    *,
    status_code: int = 200,
    json_data: Any = None,
) -> MagicMock:
    """Build a fake httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner():  # type: ignore[no-untyped-def]
    """Create a typer CliRunner."""
    _skip_if_missing()
    from typer.testing import CliRunner

    return CliRunner()


# ===========================================================================
# AC-T044-1: source list/add/update/delete commands
# ===========================================================================


class TestSourceCommands:
    """AC-T044-1: source CRUD commands."""

    @patch("intellisource.cli.main.httpx")
    def test_source_list_returns_table(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """source list should display sources in a table by default."""
        _skip_if_missing()
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "items": [
                    {
                        "id": "src-1",
                        "name": "test-rss",
                        "type": "rss",
                        "status": "active",
                    }
                ],
                "total": 1,
            }
        )

        result = runner.invoke(app, ["source", "list"])

        assert result.exit_code == 0
        assert "test-rss" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_source_add_creates_source(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """source add should create a new source via the API."""
        _skip_if_missing()
        mock_httpx.post.return_value = _mock_response(
            status_code=201,
            json_data={"id": "src-new", "name": "new-source", "type": "rss"},
        )

        result = runner.invoke(
            app,
            [
                "source",
                "add",
                "--name",
                "new-source",
                "--type",
                "rss",
                "--url",
                "https://example.com/feed",
            ],
        )

        assert result.exit_code == 0
        assert "new-source" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_source_update_modifies_source(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """source update should patch an existing source."""
        _skip_if_missing()
        mock_httpx.patch.return_value = _mock_response(
            json_data={"id": "src-1", "name": "updated-source", "type": "rss"},
        )

        result = runner.invoke(
            app, ["source", "update", "src-1", "--name", "updated-source"]
        )

        assert result.exit_code == 0
        assert "updated-source" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_source_delete_removes_source(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """source delete should remove a source via the API."""
        _skip_if_missing()
        mock_httpx.delete.return_value = _mock_response(status_code=204, json_data=None)

        result = runner.invoke(app, ["source", "delete", "src-1"])

        assert result.exit_code == 0


# ===========================================================================
# AC-T044-2: task trigger/status commands
# ===========================================================================


class TestTaskCommands:
    """AC-T044-2: task trigger and status commands."""

    @patch("intellisource.cli.main.httpx")
    def test_task_trigger_starts_collection(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """task trigger should start a collection task for a source."""
        _skip_if_missing()
        mock_httpx.post.return_value = _mock_response(
            status_code=202,
            json_data={"task_id": "task-001", "status": "pending"},
        )

        result = runner.invoke(app, ["task", "trigger", "src-1"])

        assert result.exit_code == 0
        assert "task-001" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_task_status_shows_progress(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """task status should display current task state."""
        _skip_if_missing()
        mock_httpx.get.return_value = _mock_response(
            json_data={"task_id": "task-001", "status": "running", "progress": 50},
        )

        result = runner.invoke(app, ["task", "status", "task-001"])

        assert result.exit_code == 0
        assert "running" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_task_trigger_nonexistent_source(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """task trigger for a nonexistent source should report an error."""
        _skip_if_missing()
        mock_httpx.post.return_value = _mock_response(
            status_code=404,
            json_data={"detail": "Source not found"},
        )
        mock_httpx.post.return_value.raise_for_status.side_effect = Exception(
            "404 Not Found"
        )

        result = runner.invoke(app, ["task", "trigger", "nonexistent"])

        assert result.exit_code != 0 or "not found" in result.output.lower()


# ===========================================================================
# AC-T044-3: pipeline list command
# ===========================================================================


class TestPipelineCommands:
    """AC-T044-3: pipeline list command."""

    @patch("intellisource.cli.main.httpx")
    def test_pipeline_list_shows_pipelines(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """pipeline list should display available pipelines."""
        _skip_if_missing()
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "items": [
                    {"id": "pipe-1", "name": "default-pipeline", "status": "active"}
                ],
                "total": 1,
            }
        )

        result = runner.invoke(app, ["pipeline", "list"])

        assert result.exit_code == 0
        assert "default-pipeline" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_pipeline_list_empty(self, mock_httpx: MagicMock, runner: Any) -> None:
        """pipeline list with no pipelines should display an empty result."""
        _skip_if_missing()
        mock_httpx.get.return_value = _mock_response(
            json_data={"items": [], "total": 0}
        )

        result = runner.invoke(app, ["pipeline", "list"])

        assert result.exit_code == 0


# ===========================================================================
# AC-T044-4: search command
# ===========================================================================


class TestSearchCommand:
    """AC-T044-4: search command."""

    @patch("intellisource.cli.main.httpx")
    def test_search_returns_results(self, mock_httpx: MagicMock, runner: Any) -> None:
        """search should display matching results."""
        _skip_if_missing()
        mock_httpx.post.return_value = _mock_response(
            json_data={
                "results": [{"id": "doc-1", "title": "Python Guide", "score": 0.95}],
                "total": 1,
            }
        )

        result = runner.invoke(app, ["search", "python"])

        assert result.exit_code == 0
        assert "Python Guide" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_search_no_results(self, mock_httpx: MagicMock, runner: Any) -> None:
        """search with no matches should display an appropriate message."""
        _skip_if_missing()
        mock_httpx.post.return_value = _mock_response(
            json_data={"results": [], "total": 0}
        )

        result = runner.invoke(app, ["search", "nonexistent-query-xyz"])

        assert result.exit_code == 0

    @patch("intellisource.cli.main.httpx")
    def test_search_empty_query_rejected(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """search with an empty query should fail or require a query argument."""
        _skip_if_missing()

        result = runner.invoke(app, ["search"])

        # typer should reject missing required argument
        assert result.exit_code != 0


# ===========================================================================
# AC-T044-5: output format (table default, --json)
# ===========================================================================


class TestOutputFormat:
    """AC-T044-5: table (default) and JSON (--json) output format."""

    @patch("intellisource.cli.main.httpx")
    def test_default_output_is_table(self, mock_httpx: MagicMock, runner: Any) -> None:
        """Without --json flag, output should be formatted as a table."""
        _skip_if_missing()
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "items": [
                    {
                        "id": "src-1",
                        "name": "test-rss",
                        "type": "rss",
                        "status": "active",
                    }
                ],
                "total": 1,
            }
        )

        result = runner.invoke(app, ["source", "list"])

        assert result.exit_code == 0
        # Table output should NOT be valid JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)

    @patch("intellisource.cli.main.httpx")
    def test_json_flag_outputs_json(self, mock_httpx: MagicMock, runner: Any) -> None:
        """With --json flag, output should be valid JSON."""
        _skip_if_missing()
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "items": [
                    {
                        "id": "src-1",
                        "name": "test-rss",
                        "type": "rss",
                        "status": "active",
                    }
                ],
                "total": 1,
            }
        )

        result = runner.invoke(app, ["source", "list", "--json"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, (dict, list))

    @patch("intellisource.cli.main.httpx")
    def test_json_flag_on_search(self, mock_httpx: MagicMock, runner: Any) -> None:
        """--json flag should also work on search command."""
        _skip_if_missing()
        mock_httpx.post.return_value = _mock_response(
            json_data={
                "results": [{"id": "doc-1", "title": "Result", "score": 0.9}],
                "total": 1,
            }
        )

        result = runner.invoke(app, ["search", "query", "--json"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, (dict, list))


# ===========================================================================
# AC-T044-6: API address/key via env vars or CLI args
# ===========================================================================


class TestApiConfiguration:
    """AC-T044-6: API url/key configured via env vars or CLI args."""

    @patch("intellisource.cli.main.httpx")
    def test_env_var_api_url(
        self, mock_httpx: MagicMock, runner: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IS_API_URL env var should set the API base URL."""
        _skip_if_missing()
        monkeypatch.setenv("IS_API_URL", "http://custom-api:9000")
        mock_httpx.get.return_value = _mock_response(
            json_data={"items": [], "total": 0}
        )

        result = runner.invoke(app, ["source", "list"])

        assert result.exit_code == 0
        # Verify the custom URL was used in the HTTP call
        call_args = mock_httpx.get.call_args
        assert call_args is not None
        url_arg = str(call_args[0][0]) if call_args[0] else str(call_args)
        assert "custom-api:9000" in url_arg

    @patch("intellisource.cli.main.httpx")
    def test_env_var_api_key(
        self, mock_httpx: MagicMock, runner: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IS_API_KEY env var should set the authorization header."""
        _skip_if_missing()
        monkeypatch.setenv("IS_API_KEY", "test-secret-key")
        mock_httpx.get.return_value = _mock_response(
            json_data={"items": [], "total": 0}
        )

        result = runner.invoke(app, ["source", "list"])

        assert result.exit_code == 0
        # Verify auth header was included
        call_kwargs = mock_httpx.get.call_args
        assert call_kwargs is not None
        headers = call_kwargs.kwargs.get("headers", {}) if call_kwargs.kwargs else {}
        assert "Authorization" in headers or "test-secret-key" in str(call_kwargs)

    @patch("intellisource.cli.main.httpx")
    def test_cli_arg_overrides_env_api_url(
        self, mock_httpx: MagicMock, runner: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--api-url CLI arg should override IS_API_URL env var."""
        _skip_if_missing()
        monkeypatch.setenv("IS_API_URL", "http://env-api:8000")
        mock_httpx.get.return_value = _mock_response(
            json_data={"items": [], "total": 0}
        )

        result = runner.invoke(
            app, ["--api-url", "http://cli-api:9999", "source", "list"]
        )

        assert result.exit_code == 0
        call_args = mock_httpx.get.call_args
        assert call_args is not None
        url_arg = str(call_args[0][0]) if call_args[0] else str(call_args)
        assert "cli-api:9999" in url_arg

    @patch("intellisource.cli.main.httpx")
    def test_cli_arg_overrides_env_api_key(
        self, mock_httpx: MagicMock, runner: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--api-key CLI arg should override IS_API_KEY env var."""
        _skip_if_missing()
        monkeypatch.setenv("IS_API_KEY", "env-key")
        mock_httpx.get.return_value = _mock_response(
            json_data={"items": [], "total": 0}
        )

        result = runner.invoke(app, ["--api-key", "cli-key", "source", "list"])

        assert result.exit_code == 0
        call_kwargs = mock_httpx.get.call_args
        assert call_kwargs is not None
        full_call_str = str(call_kwargs)
        assert "cli-key" in full_call_str
