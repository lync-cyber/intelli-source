"""P1-b: CLI `template` command group (list/show/add/rm)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from intellisource.cli.main import app

runner = CliRunner()


def _resp(*, status_code: int = 200, json_data: Any = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = ""
    return resp


@patch("intellisource.cli._client.httpx")
def test_template_list(mock_httpx: MagicMock) -> None:
    mock_httpx.get.return_value = _resp(
        json_data={
            "items": [
                {"name": "daily-brief", "formats": ["html"], "default_format": "html"}
            ]
        }
    )
    result = runner.invoke(app, ["template", "list"])
    assert result.exit_code == 0
    assert "daily-brief" in result.output


@patch("intellisource.cli._client.httpx")
def test_template_show(mock_httpx: MagicMock) -> None:
    mock_httpx.get.return_value = _resp(
        json_data={
            "name": "my-brief",
            "source": "db",
            "default_format": "markdown",
            "formats": ["markdown"],
        }
    )
    result = runner.invoke(app, ["template", "show", "my-brief"])
    assert result.exit_code == 0
    assert "my-brief" in result.output


@patch("intellisource.cli._client.httpx")
def test_template_show_not_found_exits_1(mock_httpx: MagicMock) -> None:
    mock_httpx.get.return_value = _resp(
        status_code=404, json_data={"detail": "not found"}
    )
    result = runner.invoke(app, ["template", "show", "ghost"])
    assert result.exit_code == 1


@patch("intellisource.cli._client.httpx")
def test_template_add_builds_expected_payload(mock_httpx: MagicMock) -> None:
    mock_httpx.post.return_value = _resp(
        status_code=201,
        json_data={
            "name": "my-brief",
            "source": "db",
            "base_template": "daily-brief",
            "default_format": "markdown",
            "formats": ["markdown"],
        },
    )
    result = runner.invoke(
        app,
        [
            "template",
            "add",
            "--name",
            "my-brief",
            "--base",
            "daily-brief",
            "--formats",
            "markdown,text",
            "--default-format",
            "markdown",
            "--source",
            "# {{ bundle.title }}",
            "--title",
            "我的速览",
        ],
    )
    assert result.exit_code == 0
    assert "my-brief" in result.output

    _, kwargs = mock_httpx.post.call_args
    payload = kwargs["json"]
    assert payload["base_template"] == "daily-brief"
    assert payload["formats"] == ["markdown", "text"]
    assert payload["jinja_source"] == {"markdown": "# {{ bundle.title }}"}
    assert payload["aggregate_config"] == {"title": "我的速览"}


@patch("intellisource.cli._client.httpx")
def test_template_add_error_exits_1(mock_httpx: MagicMock) -> None:
    mock_httpx.post.return_value = _resp(
        status_code=422, json_data={"detail": "base_template 'ghost' is not known"}
    )
    result = runner.invoke(
        app,
        [
            "template",
            "add",
            "--name",
            "x",
            "--base",
            "ghost",
            "--formats",
            "markdown",
            "--default-format",
            "markdown",
        ],
    )
    assert result.exit_code == 1
    assert "422" in result.output


@patch("intellisource.cli._client.httpx")
def test_template_rm(mock_httpx: MagicMock) -> None:
    mock_httpx.delete.return_value = _resp(status_code=204, json_data=None)
    result = runner.invoke(app, ["template", "rm", "my-brief"])
    assert result.exit_code == 0
    assert "Deleted" in result.output


@patch("intellisource.cli._client.httpx")
def test_template_rm_not_found_exits_1(mock_httpx: MagicMock) -> None:
    mock_httpx.delete.return_value = _resp(
        status_code=404, json_data={"detail": "not found"}
    )
    result = runner.invoke(app, ["template", "rm", "ghost"])
    assert result.exit_code == 1
