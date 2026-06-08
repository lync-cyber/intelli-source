"""Tests for `intellisource pipeline` + `topic show` CLI subcommands."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from intellisource.cli.main import app


def _mock_response(*, status_code: int = 200, json_data: Any = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = json.dumps(json_data) if json_data is not None else ""
    return resp


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# pipeline show
# ---------------------------------------------------------------------------


class TestPipelineShow:
    @patch("intellisource.cli._client.httpx")
    def test_show_renders_detail(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "name": "default",
                "mode": "flexible",
                "max_steps": 50,
                "on_failure": "abort",
            }
        )
        result = runner.invoke(app, ["pipeline", "show", "default"])
        assert result.exit_code == 0
        assert mock_httpx.get.call_args.args[0].endswith("/api/v1/pipelines/default")
        assert "name: default" in result.stdout

    @patch("intellisource.cli._client.httpx")
    def test_show_json_flag_emits_json(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.get.return_value = _mock_response(
            json_data={"name": "default", "mode": "flexible", "max_steps": 50}
        )
        result = runner.invoke(app, ["pipeline", "show", "default", "--json"])
        assert result.exit_code == 0
        body = json.loads(result.stdout.strip())
        assert body["mode"] == "flexible"

    @patch("intellisource.cli._client.httpx")
    def test_show_404_exits_1(self, mock_httpx: MagicMock, runner: CliRunner) -> None:
        mock_httpx.get.return_value = _mock_response(status_code=404)
        result = runner.invoke(app, ["pipeline", "show", "ghost"])
        assert result.exit_code == 1
        assert "Not found" in result.stdout


# ---------------------------------------------------------------------------
# pipeline run
# ---------------------------------------------------------------------------


class TestPipelineRun:
    @patch("intellisource.cli._client.httpx")
    def test_run_posts_to_run_endpoint(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            json_data={"task_id": "t-1", "task_chain_id": "c-1"}
        )
        result = runner.invoke(app, ["pipeline", "run", "default", "--json"])
        assert result.exit_code == 0, result.stdout
        url = mock_httpx.post.call_args.args[0]
        assert url.endswith("/api/v1/pipelines/default/run")
        body = json.loads(result.stdout.strip())
        assert body["task_id"] == "t-1"
        assert body["task_chain_id"] == "c-1"

    @patch("intellisource.cli._client.httpx")
    def test_run_with_params_sends_parsed_json(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            json_data={"task_id": "t-1", "task_chain_id": "c-1"}
        )
        result = runner.invoke(
            app, ["pipeline", "run", "default", "--params", '{"limit": 10}']
        )
        assert result.exit_code == 0, result.stdout
        payload = mock_httpx.post.call_args.kwargs["json"]
        assert payload["params"] == {"limit": 10}

    @patch("intellisource.cli._client.httpx")
    def test_run_invalid_params_exits_2(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(
            app, ["pipeline", "run", "default", "--params", "not-json"]
        )
        assert result.exit_code == 2
        assert "--params must be valid JSON" in result.stdout
        mock_httpx.post.assert_not_called()

    @patch("intellisource.cli._client.httpx")
    def test_run_404_exits_1(self, mock_httpx: MagicMock, runner: CliRunner) -> None:
        mock_httpx.post.return_value = _mock_response(
            status_code=404, json_data={"detail": "pipeline 'ghost' not found"}
        )
        result = runner.invoke(app, ["pipeline", "run", "ghost"])
        assert result.exit_code == 1
        assert "Not found" in result.stdout


# ---------------------------------------------------------------------------
# pipeline create
# ---------------------------------------------------------------------------


class TestPipelineCreate:
    @patch("intellisource.cli._client.httpx")
    def test_create_posts_pipeline_config_payload(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            status_code=201,
            json_data={"name": "p1", "mode": "flexible", "max_steps": 50},
        )
        result = runner.invoke(
            app,
            [
                "pipeline",
                "create",
                "--name",
                "p1",
                "--mode",
                "flexible",
                "--steps",
                '[{"tool": "collect"}]',
                "--tools-allowed",
                "collect, process",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout
        call = mock_httpx.post.call_args
        assert call.args[0].endswith("/api/v1/pipelines")
        payload = call.kwargs["json"]
        assert payload["name"] == "p1"
        assert payload["mode"] == "flexible"
        assert payload["steps"] == [{"tool": "collect"}]
        assert payload["tools_allowed"] == ["collect", "process"]
        assert payload["agent_mode"] == "process"

    @patch("intellisource.cli._client.httpx")
    def test_create_invalid_steps_json_exits_2(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(
            app,
            ["pipeline", "create", "--name", "p1", "--steps", "not-json"],
        )
        assert result.exit_code == 2
        assert "--steps must be valid JSON" in result.stdout
        mock_httpx.post.assert_not_called()

    @patch("intellisource.cli._client.httpx")
    def test_create_propagates_422_with_validator_message(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            status_code=422, json_data={"detail": "Invalid mode 'bogus'."}
        )
        result = runner.invoke(
            app,
            ["pipeline", "create", "--name", "p1", "--mode", "bogus"],
        )
        assert result.exit_code == 1
        assert "422" in result.stdout
        assert "Invalid mode" in result.stdout


# ---------------------------------------------------------------------------
# pipeline update
# ---------------------------------------------------------------------------


class TestPipelineUpdate:
    @patch("intellisource.cli._client.httpx")
    def test_update_sends_only_provided_fields(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.patch.return_value = _mock_response(
            json_data={"name": "p1", "mode": "strict"}
        )
        result = runner.invoke(
            app,
            [
                "pipeline",
                "update",
                "p1",
                "--mode",
                "strict",
                "--max-steps",
                "10",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout
        url = mock_httpx.patch.call_args.args[0]
        assert url.endswith("/api/v1/pipelines/p1")
        body = mock_httpx.patch.call_args.kwargs["json"]
        assert body == {"mode": "strict", "max_steps": 10}, "patch must omit unset"

    @patch("intellisource.cli._client.httpx")
    def test_update_steps_parsed_from_json(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.patch.return_value = _mock_response(json_data={"name": "p1"})
        result = runner.invoke(
            app,
            ["pipeline", "update", "p1", "--steps", '[{"processor": "filter"}]'],
        )
        assert result.exit_code == 0, result.stdout
        body = mock_httpx.patch.call_args.kwargs["json"]
        assert body["steps"] == [{"processor": "filter"}]

    @patch("intellisource.cli._client.httpx")
    def test_update_no_fields_exits_2(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(app, ["pipeline", "update", "p1"])
        assert result.exit_code == 2
        assert "Nothing to update" in result.stdout
        mock_httpx.patch.assert_not_called()

    @patch("intellisource.cli._client.httpx")
    def test_update_invalid_steps_json_exits_2(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(app, ["pipeline", "update", "p1", "--steps", "not-json"])
        assert result.exit_code == 2
        assert "--steps must be valid JSON" in result.stdout
        mock_httpx.patch.assert_not_called()

    @patch("intellisource.cli._client.httpx")
    def test_update_404_exits_1(self, mock_httpx: MagicMock, runner: CliRunner) -> None:
        mock_httpx.patch.return_value = _mock_response(status_code=404)
        result = runner.invoke(app, ["pipeline", "update", "ghost", "--mode", "strict"])
        assert result.exit_code == 1
        assert "Not found" in result.stdout


# ---------------------------------------------------------------------------
# pipeline rm
# ---------------------------------------------------------------------------


class TestPipelineRm:
    @patch("intellisource.cli._client.httpx")
    def test_rm_calls_delete_endpoint(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.delete.return_value = _mock_response(status_code=204)
        result = runner.invoke(app, ["pipeline", "rm", "p1"])
        assert result.exit_code == 0
        assert "Deleted" in result.stdout
        url = mock_httpx.delete.call_args.args[0]
        assert url.endswith("/api/v1/pipelines/p1")

    @patch("intellisource.cli._client.httpx")
    def test_rm_404_exits_1(self, mock_httpx: MagicMock, runner: CliRunner) -> None:
        mock_httpx.delete.return_value = _mock_response(status_code=404)
        result = runner.invoke(app, ["pipeline", "rm", "ghost"])
        assert result.exit_code == 1
        assert "Not found" in result.stdout


# ---------------------------------------------------------------------------
# topic show
# ---------------------------------------------------------------------------


class TestTopicShow:
    @patch("intellisource.cli._client.httpx")
    def test_show_renders_detail(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "id": "artificial-intelligence",
                "name": "人工智能",
                "dimension": "discipline",
                "source_count": 3,
                "sources": [{"name": "arXiv", "type": "rss"}],
            }
        )
        result = runner.invoke(app, ["topic", "show", "artificial-intelligence"])
        assert result.exit_code == 0
        assert mock_httpx.get.call_args.args[0].endswith(
            "/api/v1/topics/artificial-intelligence"
        )
        assert "id: artificial-intelligence" in result.stdout

    @patch("intellisource.cli._client.httpx")
    def test_show_json_flag_emits_json(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.get.return_value = _mock_response(
            json_data={"id": "ai", "name": "AI", "source_count": 2}
        )
        result = runner.invoke(app, ["topic", "show", "ai", "--json"])
        assert result.exit_code == 0
        body = json.loads(result.stdout.strip())
        assert body["id"] == "ai"

    @patch("intellisource.cli._client.httpx")
    def test_show_404_exits_1(self, mock_httpx: MagicMock, runner: CliRunner) -> None:
        mock_httpx.get.return_value = _mock_response(
            status_code=404, json_data={"error": {"message": "topic not found"}}
        )
        result = runner.invoke(app, ["topic", "show", "ghost"])
        assert result.exit_code == 1
        assert "Not found" in result.stdout
