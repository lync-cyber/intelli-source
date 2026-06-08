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
import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
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
# chat command: RAG conversation over POST /search/chat
# ===========================================================================


def _chat_response(
    *,
    answer: str = "Python is a programming language.",
    session_id: str = "sess-1",
    sources: list[dict[str, Any]] | None = None,
) -> MagicMock:
    return _mock_response(
        json_data={
            "session_id": session_id,
            "answer": answer,
            "sources": sources
            if sources is not None
            else [{"title": "Python Guide", "url": "https://example.com/py"}],
            "query_time_ms": 12,
            "steps_executed": 2,
            "task_chain_id": "tc-1",
        }
    )


class TestChatCommand:
    """chat command wraps POST /search/chat (single-shot + interactive REPL)."""

    @patch("intellisource.cli.main.httpx")
    def test_chat_single_shot_prints_answer_and_sources(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """chat MESSAGE should POST /search/chat and print the answer + sources."""
        _skip_if_missing()
        mock_httpx.post.return_value = _chat_response()

        result = runner.invoke(app, ["chat", "what is python"])

        assert result.exit_code == 0
        assert "Python is a programming language." in result.output
        assert "Python Guide" in result.output
        url = mock_httpx.post.call_args.args[0]
        assert url.endswith("/api/v1/search/chat")
        assert mock_httpx.post.call_args.kwargs["json"]["message"] == "what is python"

    @patch("intellisource.cli.main.httpx")
    def test_chat_json_output_emits_raw_body(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """--json should emit the raw response body for scripting."""
        _skip_if_missing()
        mock_httpx.post.return_value = _chat_response(answer="hi", sources=[])

        result = runner.invoke(app, ["chat", "hi", "--json"])

        assert result.exit_code == 0
        assert json.loads(result.output)["answer"] == "hi"

    @patch("intellisource.cli.main.httpx")
    def test_chat_session_id_forwarded(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """--session-id continues an existing conversation server-side."""
        _skip_if_missing()
        mock_httpx.post.return_value = _chat_response(session_id="sess-9")

        result = runner.invoke(app, ["chat", "again", "--session-id", "sess-9"])

        assert result.exit_code == 0
        assert mock_httpx.post.call_args.kwargs["json"]["session_id"] == "sess-9"

    @patch("intellisource.cli.main.httpx")
    def test_chat_error_response_exits_nonzero(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """A 503 from the API surfaces the error message and exits non-zero."""
        _skip_if_missing()
        mock_httpx.post.return_value = _mock_response(
            status_code=503,
            json_data={"error": {"message": "agent_runner not initialised"}},
        )

        result = runner.invoke(app, ["chat", "hello"])

        assert result.exit_code == 1
        assert "agent_runner not initialised" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_chat_interactive_repl_carries_session(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        """REPL answers each turn and reuses the session id captured from the reply."""
        _skip_if_missing()
        mock_httpx.post.return_value = _chat_response(
            answer="answer-A", session_id="sess-repl", sources=[]
        )

        result = runner.invoke(app, ["chat"], input="first\nsecond\n\n")

        assert result.exit_code == 0
        assert "answer-A" in result.output
        assert mock_httpx.post.call_count == 2
        # the second turn carries the session id returned by the first reply
        assert mock_httpx.post.call_args.kwargs["json"]["message"] == "second"
        assert mock_httpx.post.call_args.kwargs["json"]["session_id"] == "sess-repl"


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


# ===========================================================================
# Cross-platform docker compose lifecycle commands (up/down/migrate/logs/ps)
# ===========================================================================


class TestComposeCommands:
    """up/down/migrate/logs/ps wrap `docker compose` via subprocess."""

    @patch("intellisource.cli.main.subprocess")
    def test_up_runs_compose_up_detached(
        self, mock_subprocess: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, ["up"])

        assert result.exit_code == 0
        argv = mock_subprocess.run.call_args[0][0]
        assert argv[:2] == ["docker", "compose"]
        # --wait blocks until healthchecks pass so a follow-up check-api does
        # not race the API boot window.
        assert argv[-3:] == ["up", "-d", "--wait"]
        # never shell=True — Windows path quoting safety
        assert mock_subprocess.run.call_args.kwargs.get("shell", False) is False

    @patch("intellisource.cli.main.subprocess")
    def test_compose_file_is_absolute_anchored_path(
        self, mock_subprocess: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, ["up"])

        assert result.exit_code == 0
        argv = mock_subprocess.run.call_args[0][0]
        assert argv[2] == "-f"
        compose_path = pathlib.Path(argv[3])
        assert compose_path.is_absolute()
        assert compose_path.name == "docker-compose.yml"
        assert compose_path.parent.name == "docker"

    @patch("intellisource.cli.main.subprocess")
    def test_down_runs_compose_down(
        self, mock_subprocess: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, ["down"])

        assert result.exit_code == 0
        assert mock_subprocess.run.call_args[0][0][-1] == "down"

    @patch("intellisource.cli.main.subprocess")
    def test_migrate_runs_compose_run_migrate(
        self, mock_subprocess: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, ["migrate"])

        assert result.exit_code == 0
        assert mock_subprocess.run.call_args[0][0][-3:] == ["run", "--rm", "migrate"]

    @patch("intellisource.cli.main.subprocess")
    def test_nonzero_exit_code_propagates(
        self, mock_subprocess: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()
        mock_subprocess.run.return_value = MagicMock(returncode=2)

        result = runner.invoke(app, ["up"])

        assert result.exit_code == 2

    @patch("intellisource.cli.main.subprocess")
    def test_docker_missing_shows_friendly_error(
        self, mock_subprocess: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()
        mock_subprocess.run.side_effect = FileNotFoundError()

        result = runner.invoke(app, ["up"])

        assert result.exit_code == 1
        assert "docker" in result.output.lower()


# ===========================================================================
# init hardening: anchoring / provider validation / template seeding / -y mode
# ===========================================================================


def _seed_example_tree(root: pathlib.Path) -> None:
    """Create the minimal example files init's seeding expects under *root*."""
    (root / "docker").mkdir(parents=True, exist_ok=True)
    (root / "docker" / ".env.example").write_text("IS_API_KEY=\n", encoding="utf-8")
    (root / "config" / "examples").mkdir(parents=True, exist_ok=True)
    (root / "config" / "examples" / "llm_models.example.yaml").write_text(
        "default_model:\n  model: deepseek/deepseek-v4-flash\n", encoding="utf-8"
    )
    (root / "config" / "examples" / "subscriptions.example.yaml").write_text(
        "subscriptions: []\n", encoding="utf-8"
    )


class TestInitHardening:
    """init: path anchoring, provider validation, template seeding, -y mode."""

    @patch("intellisource.cli.main.project_root")
    def test_non_interactive_generates_core_files(
        self, mock_root: MagicMock, runner: Any, tmp_path: pathlib.Path
    ) -> None:
        _skip_if_missing()
        mock_root.return_value = tmp_path
        _seed_example_tree(tmp_path)

        result = runner.invoke(
            app, ["init", "--non-interactive", "--provider", "deepseek"]
        )

        assert result.exit_code == 0, result.output
        assert (tmp_path / "docker" / ".env").is_file()
        # provider-consistency fix: llm_models.yaml seeded from the example
        assert (tmp_path / "config" / "llm_models.yaml").is_file()
        assert (tmp_path / "config" / "sources" / "sources.yaml").is_file()

    @patch("intellisource.cli.main.project_root")
    def test_non_interactive_writes_generated_api_key(
        self,
        mock_root: MagicMock,
        runner: Any,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _skip_if_missing()
        mock_root.return_value = tmp_path
        _seed_example_tree(tmp_path)
        monkeypatch.delenv("IS_API_KEY", raising=False)

        result = runner.invoke(app, ["init", "--non-interactive"])

        assert result.exit_code == 0, result.output
        env_text = (tmp_path / "docker" / ".env").read_text(encoding="utf-8")
        key_line = next(
            ln for ln in env_text.splitlines() if ln.startswith("IS_API_KEY=")
        )
        assert key_line.split("=", 1)[1] not in ("", "change-me-in-production")

    @patch("intellisource.cli.main.project_root")
    def test_invalid_provider_rejected_without_writing(
        self, mock_root: MagicMock, runner: Any, tmp_path: pathlib.Path
    ) -> None:
        _skip_if_missing()
        mock_root.return_value = tmp_path
        _seed_example_tree(tmp_path)

        result = runner.invoke(
            app, ["init", "--non-interactive", "--provider", "bogus"]
        )

        assert result.exit_code != 0
        assert not (tmp_path / "docker" / ".env").exists()

    @patch("intellisource.cli.main.project_root")
    def test_seeding_is_idempotent(
        self, mock_root: MagicMock, runner: Any, tmp_path: pathlib.Path
    ) -> None:
        _skip_if_missing()
        mock_root.return_value = tmp_path
        _seed_example_tree(tmp_path)
        # a pre-existing user llm_models.yaml must not be overwritten
        (tmp_path / "config" / "llm_models.yaml").write_text(
            "default_model:\n  model: custom\n", encoding="utf-8"
        )

        result = runner.invoke(app, ["init", "--non-interactive"])

        assert result.exit_code == 0, result.output
        assert "custom" in (tmp_path / "config" / "llm_models.yaml").read_text(
            encoding="utf-8"
        )

    @patch("intellisource.cli.main.project_root")
    def test_interactive_reprompts_invalid_provider_choice(
        self, mock_root: MagicMock, runner: Any, tmp_path: pathlib.Path
    ) -> None:
        _skip_if_missing()
        mock_root.return_value = tmp_path
        _seed_example_tree(tmp_path)
        # API key blank (auto-gen) -> provider "9" invalid -> "1" deepseek ->
        # llm key -> channel "4" skip -> add starter "y"
        result = runner.invoke(app, ["init"], input="\n9\n1\nsk-test\n4\ny\n")

        assert result.exit_code == 0, result.output
        assert "Invalid choice" in result.output
        env_text = (tmp_path / "docker" / ".env").read_text(encoding="utf-8")
        assert "DEEPSEEK_API_KEY=sk-test" in env_text


# ===========================================================================
# doctor config self-check
# ===========================================================================


class TestDoctorChecks:
    """doctor's offline _doctor_env logic + command surface."""

    def test_placeholder_api_key_flagged(self) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _doctor_env

        items = _doctor_env({"IS_API_KEY": "change-me-in-production"})
        api = next(i for i in items if i[0] == "IS_API_KEY")
        assert api[1] is False

    def test_database_url_requires_asyncpg_driver(self) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _doctor_env

        items = _doctor_env({"IS_DATABASE_URL": "postgresql://u:p@h/db"})
        db = next(i for i in items if i[0] == "IS_DATABASE_URL")
        assert db[1] is False
        assert "asyncpg" in db[2]

    def test_database_url_asyncpg_accepted(self) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _doctor_env

        items = _doctor_env({"IS_DATABASE_URL": "postgresql+asyncpg://u:p@h/db"})
        db = next(i for i in items if i[0] == "IS_DATABASE_URL")
        assert db[1] is True

    def test_subscriptions_dir_and_llm_config_checked(self) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _doctor_env

        labels = [i[0] for i in _doctor_env({})]
        assert any("subscriptions dir" in label for label in labels)
        assert any(label.startswith("llm config") for label in labels)

    def test_channel_reported_optional(self) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _doctor_env

        items = _doctor_env({})
        wework = next(i for i in items if i[0] == "channel wework")
        assert wework[1] is None

    @patch("intellisource.cli.main.project_root")
    def test_doctor_command_runs_offline(
        self, mock_root: MagicMock, runner: Any, tmp_path: pathlib.Path
    ) -> None:
        _skip_if_missing()
        mock_root.return_value = tmp_path
        (tmp_path / "docker").mkdir()
        (tmp_path / "docker" / ".env").write_text(
            "IS_API_KEY=real-key\n", encoding="utf-8"
        )

        result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Inspecting" in result.output

    @patch("intellisource.cli.main.project_root")
    def test_doctor_strict_exits_nonzero_when_config_missing(
        self, mock_root: MagicMock, runner: Any, tmp_path: pathlib.Path
    ) -> None:
        _skip_if_missing()
        mock_root.return_value = tmp_path
        (tmp_path / "docker").mkdir()
        (tmp_path / "docker" / ".env").write_text(
            "IS_API_KEY=change-me-in-production\n", encoding="utf-8"
        )

        result = runner.invoke(app, ["doctor", "--strict"])

        assert result.exit_code == 1


# ===========================================================================
# doctor --check-api: boot-window-aware health probe
# ===========================================================================


def _health_response(status: str = "healthy", **extra: Any) -> MagicMock:
    """A 200 response whose body decodes to a health payload."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"status": status, **extra}
    return resp


def _empty_body_response() -> MagicMock:
    """A 200 response whose body is empty (``resp.json()`` raises).

    This is the boot-window shape: docker-proxy answers the published port
    before uvicorn serves, so the body is empty and JSON decoding fails with
    ``Expecting value: line 1 column 1 (char 0)``.
    """
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
    return resp


_CLEAN_ENV_KEYS = (
    "IS_API_KEY",
    "IS_DATABASE_URL",
    "IS_REDIS_URL",
    "IS_CELERY_BROKER_URL",
    "IS_LLM_CONFIG_PATH",
    "IS_SOURCE_CONFIG_DIR",
    "IS_SUBSCRIPTION_CONFIG_DIR",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


def _seed_doctor_clean_tree(root: pathlib.Path) -> None:
    """Populate *root* so ``_doctor_env`` reports zero required-item errors."""
    (root / "docker").mkdir(parents=True, exist_ok=True)
    (root / "docker" / ".env").write_text(
        "IS_API_KEY=real-key\n"
        "IS_DATABASE_URL=postgresql+asyncpg://u:p@h:5432/db\n"
        "IS_REDIS_URL=redis://h:6379/0\n"
        "IS_CELERY_BROKER_URL=redis://h:6379/0\n"
        "DEEPSEEK_API_KEY=sk-test\n",
        encoding="utf-8",
    )
    (root / "config" / "sources").mkdir(parents=True, exist_ok=True)
    (root / "config" / "sources" / "s.yaml").write_text(
        "sources: []\n", encoding="utf-8"
    )
    (root / "config" / "subscriptions").mkdir(parents=True, exist_ok=True)
    (root / "config" / "subscriptions" / "s.yaml").write_text(
        "subscriptions: []\n", encoding="utf-8"
    )
    (root / "config" / "llm_models.yaml").write_text(
        "default_model:\n  model: deepseek/deepseek-v4-flash\n", encoding="utf-8"
    )


class TestProbeApiHealth:
    """_probe_api_health classifies ok / starting / down and retries."""

    @patch("intellisource.cli.main.httpx.get")
    def test_ok_returns_decoded_body(self, mock_get: MagicMock) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _probe_api_health

        mock_get.return_value = _health_response("healthy")

        outcome, payload = _probe_api_health(attempts=3, backoff=0)

        assert outcome == "ok"
        assert isinstance(payload, dict)
        assert payload["status"] == "healthy"

    @patch("intellisource.cli.main.httpx.get")
    def test_empty_body_is_starting_after_retries(self, mock_get: MagicMock) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _probe_api_health

        mock_get.return_value = _empty_body_response()

        outcome, payload = _probe_api_health(attempts=3, backoff=0)

        assert outcome == "starting"
        assert "JSON" in str(payload)
        # exhausted all attempts before giving up
        assert mock_get.call_count == 3

    @patch("intellisource.cli.main.httpx.get")
    def test_5xx_is_starting(self, mock_get: MagicMock) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _probe_api_health

        resp = MagicMock()
        resp.status_code = 503
        mock_get.return_value = resp

        outcome, payload = _probe_api_health(attempts=2, backoff=0)

        assert outcome == "starting"
        assert "503" in str(payload)

    @patch("intellisource.cli.main.httpx.get")
    def test_connect_error_is_down(self, mock_get: MagicMock) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _probe_api_health

        mock_get.side_effect = httpx.ConnectError("connection refused")

        outcome, payload = _probe_api_health(attempts=2, backoff=0)

        assert outcome == "down"
        assert "refused" in str(payload)
        assert mock_get.call_count == 2

    @patch("intellisource.cli.main.httpx.get")
    def test_read_timeout_is_starting(self, mock_get: MagicMock) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _probe_api_health

        mock_get.side_effect = httpx.ReadTimeout("read timed out")

        outcome, _ = _probe_api_health(attempts=2, backoff=0)

        assert outcome == "starting"

    @patch("intellisource.cli.main.httpx.get")
    def test_retries_then_succeeds(self, mock_get: MagicMock) -> None:
        _skip_if_missing()
        from intellisource.cli.main import _probe_api_health

        # boot window on the first probe, serving on the second
        mock_get.side_effect = [_empty_body_response(), _health_response("healthy")]

        outcome, payload = _probe_api_health(attempts=5, backoff=0)

        assert outcome == "ok"
        assert isinstance(payload, dict)
        assert mock_get.call_count == 2


class TestDoctorCheckApi:
    """doctor --check-api surfaces ok / starting / down distinctly."""

    @patch("intellisource.cli.main.time.sleep")
    @patch("intellisource.cli.main.httpx.get")
    @patch("intellisource.cli.main.project_root")
    def test_check_api_ok_reports_status(
        self,
        mock_root: MagicMock,
        mock_get: MagicMock,
        _mock_sleep: MagicMock,
        runner: Any,
        tmp_path: pathlib.Path,
    ) -> None:
        _skip_if_missing()
        mock_root.return_value = tmp_path
        (tmp_path / "docker").mkdir()
        (tmp_path / "docker" / ".env").write_text(
            "IS_API_KEY=real-key\n", encoding="utf-8"
        )
        mock_get.return_value = _health_response("healthy")

        result = runner.invoke(app, ["doctor", "--check-api"])

        assert result.exit_code == 0
        assert "[OK]" in result.output
        assert "healthy" in result.output

    @patch("intellisource.cli.main.time.sleep")
    @patch("intellisource.cli.main.httpx.get")
    @patch("intellisource.cli.main.project_root")
    def test_check_api_down_reports_unreachable(
        self,
        mock_root: MagicMock,
        mock_get: MagicMock,
        _mock_sleep: MagicMock,
        runner: Any,
        tmp_path: pathlib.Path,
    ) -> None:
        _skip_if_missing()
        mock_root.return_value = tmp_path
        (tmp_path / "docker").mkdir()
        (tmp_path / "docker" / ".env").write_text(
            "IS_API_KEY=real-key\n", encoding="utf-8"
        )
        mock_get.side_effect = httpx.ConnectError("connection refused")

        result = runner.invoke(app, ["doctor", "--check-api"])

        assert "[FAIL]" in result.output
        assert "unreachable" in result.output
        assert "intellisource up" in result.output

    @patch("intellisource.cli.main.time.sleep")
    @patch("intellisource.cli.main.httpx.get")
    @patch("intellisource.cli.main.project_root")
    def test_check_api_starting_is_soft_note_in_non_strict(
        self,
        mock_root: MagicMock,
        mock_get: MagicMock,
        _mock_sleep: MagicMock,
        runner: Any,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _skip_if_missing()
        for key in _CLEAN_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_root.return_value = tmp_path
        _seed_doctor_clean_tree(tmp_path)
        mock_get.return_value = _empty_body_response()

        result = runner.invoke(app, ["doctor", "--check-api"])

        assert result.exit_code == 0
        assert "starting up" in result.output
        assert "[FAIL]" not in result.output

    @patch("intellisource.cli.main.time.sleep")
    @patch("intellisource.cli.main.httpx.get")
    @patch("intellisource.cli.main.project_root")
    def test_check_api_starting_fails_gate_in_strict(
        self,
        mock_root: MagicMock,
        mock_get: MagicMock,
        _mock_sleep: MagicMock,
        runner: Any,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _skip_if_missing()
        for key in _CLEAN_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_root.return_value = tmp_path
        _seed_doctor_clean_tree(tmp_path)
        mock_get.return_value = _empty_body_response()

        result = runner.invoke(app, ["doctor", "--check-api", "--strict"])

        assert result.exit_code == 1
        assert "starting up" in result.output


# ===========================================================================
# source show / update-fields / versions / diff
# ===========================================================================


class TestSourceShowVersionsDiff:
    @patch("intellisource.cli.main.httpx")
    def test_source_show_renders_detail(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "id": "src-1",
                "name": "hn",
                "type": "rss",
                "url": "https://example.com/feed",
                "tags": ["ai", "tech"],
            }
        )
        result = runner.invoke(app, ["source", "show", "src-1"])
        assert result.exit_code == 0
        assert mock_httpx.get.call_args.args[0].endswith("/api/v1/sources/src-1")
        assert "name: hn" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_source_show_404_exits_1(self, mock_httpx: MagicMock, runner: Any) -> None:
        _skip_if_missing()
        mock_httpx.get.return_value = _mock_response(status_code=404)
        result = runner.invoke(app, ["source", "show", "missing"])
        assert result.exit_code == 1
        assert "Not found" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_source_update_sends_url_type_tags_schedule(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()
        mock_httpx.patch.return_value = _mock_response(
            json_data={"id": "src-1", "name": "hn"}
        )
        result = runner.invoke(
            app,
            [
                "source",
                "update",
                "src-1",
                "--url",
                "https://new.example.com/feed",
                "--type",
                "api",
                "--tags",
                "ai, security",
                "--schedule-interval",
                "1800",
            ],
        )
        assert result.exit_code == 0, result.output
        body = mock_httpx.patch.call_args.kwargs["json"]
        assert body["url"] == "https://new.example.com/feed"
        assert body["type"] == "api"
        assert body["tags"] == ["ai", "security"]
        assert body["schedule_interval"] == 1800

    @patch("intellisource.cli.main.httpx")
    def test_source_update_no_fields_exits_2(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()
        result = runner.invoke(app, ["source", "update", "src-1"])
        assert result.exit_code == 2
        assert "Nothing to update" in result.output
        mock_httpx.patch.assert_not_called()

    @patch("intellisource.cli.main.httpx")
    def test_source_versions_lists(self, mock_httpx: MagicMock, runner: Any) -> None:
        _skip_if_missing()
        mock_httpx.get.return_value = _mock_response(
            json_data={"versions": [{"version": "1", "config_count": 2}]}
        )
        result = runner.invoke(app, ["source", "versions"])
        assert result.exit_code == 0
        assert "config/versions" in mock_httpx.get.call_args.args[0]
        assert "config_count" in result.output

    @patch("intellisource.cli.main.httpx")
    def test_source_diff_marks_preserve(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "yaml_only": ["fresh"],
                "db_only": ["kept"],
                "both": [],
                "db_only_action": "preserve",
            }
        )
        result = runner.invoke(app, ["source", "diff"])
        assert result.exit_code == 0
        assert "reload will PRESERVE" in result.output
        assert "kept" in result.output


# ===========================================================================
# config status (aggregated yaml↔DB drift across both domains)
# ===========================================================================


class TestConfigStatus:
    @patch("intellisource.cli.main.httpx")
    def test_config_status_aggregates_both_domains(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()

        def _get(url: str, **_: Any) -> MagicMock:
            if "sources/config/diff" in url:
                return _mock_response(
                    json_data={
                        "yaml_only": ["s1"],
                        "db_only": ["s2"],
                        "both": [],
                        "db_only_action": "preserve",
                    }
                )
            if "sources/config/versions" in url:
                return _mock_response(json_data={"versions": [{"version": "3"}]})
            if "subscriptions/config/diff" in url:
                return _mock_response(
                    json_data={
                        "yaml_only": [],
                        "db_only": ["sub-x"],
                        "both": ["sub-y"],
                        "db_only_action": "pause",
                    }
                )
            if "subscriptions/config/versions" in url:
                return _mock_response(json_data={"versions": [{"version": "5"}]})
            return _mock_response(json_data={})

        mock_httpx.get.side_effect = _get
        result = runner.invoke(app, ["config", "status"])
        assert result.exit_code == 0, result.output
        out = result.output
        assert "== sources (yaml ↔ DB) ==" in out
        assert "latest recorded version: 3" in out
        assert "reload will PRESERVE" in out
        assert "== subscriptions (yaml ↔ DB) ==" in out
        assert "latest recorded version: 5" in out
        assert "reload will PAUSE" in out

    @patch("intellisource.cli.main.httpx")
    def test_config_status_handles_diff_error(
        self, mock_httpx: MagicMock, runner: Any
    ) -> None:
        _skip_if_missing()

        def _get(url: str, **_: Any) -> MagicMock:
            if "config/diff" in url:
                return _mock_response(status_code=400, json_data={"detail": "boom"})
            return _mock_response(json_data={"versions": []})

        mock_httpx.get.side_effect = _get
        result = runner.invoke(app, ["config", "status"])
        assert result.exit_code == 0
        assert "diff unavailable" in result.output
        assert "latest recorded version: (none)" in result.output


class TestRunEntrypoint:
    """The console-script ``run`` wrapper enters UTF-8 mode before dispatching."""

    def test_run_reexecs_then_invokes_app(self) -> None:
        _skip_if_missing()
        from intellisource.cli import main as cli_main

        order: list[str] = []
        with (
            patch.object(
                cli_main,
                "reexec_in_utf8_mode_if_needed",
                side_effect=lambda: order.append("reexec"),
            ),
            patch.object(cli_main, "app", side_effect=lambda: order.append("app")),
        ):
            cli_main.run()

        assert order == ["reexec", "app"]
