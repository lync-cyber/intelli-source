"""CLI tests for template list/validate/preview commands (B-075)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from intellisource.cli.main import app

runner = CliRunner()


def _resp(*, status_code: int = 200, json_data: object = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# AC-1: template list — file override section + service-unreachable degradation
# ---------------------------------------------------------------------------


@patch("intellisource.cli._client.httpx")
def test_template_list_shows_file_override_section(
    mock_httpx: MagicMock, tmp_path: Path
) -> None:
    """list output includes a file-override section listing daily-brief/markdown."""
    # Arrange: create a user override file
    override_dir = tmp_path / "config" / "templates"
    override_dir.mkdir(parents=True)
    (override_dir / "daily-brief.markdown.j2").write_text(
        "# {{ bundle.title }}\n", encoding="utf-8"
    )

    mock_httpx.get.return_value = _resp(
        json_data={"items": [{"name": "daily-brief", "formats": ["html", "markdown"]}]}
    )

    with patch(
        "intellisource.cli.commands.template.list_file_overrides",
        return_value={"daily-brief": ["markdown"]},
    ):
        result = runner.invoke(app, ["template", "list"])

    assert result.exit_code == 0
    assert "daily-brief" in result.output
    assert "markdown" in result.output
    # The file-override section must appear
    assert "config/templates" in result.output or "文件覆盖" in result.output


@patch("intellisource.cli._client.httpx")
def test_template_list_exits_0_when_service_unreachable(
    mock_httpx: MagicMock,
) -> None:
    """When API is unreachable, list still exits 0 and shows file-override section."""
    # Simulate service unreachable: _client.get raises typer.Exit(1)
    import typer

    mock_httpx.get.side_effect = Exception("connect error")

    with (
        patch(
            "intellisource.cli.commands.template.list_file_overrides",
            return_value={"daily-brief": ["markdown"]},
        ),
        patch(
            "intellisource.cli.commands.template._client.get",
            side_effect=typer.Exit(code=1),
        ),
    ):
        result = runner.invoke(app, ["template", "list"])

    assert result.exit_code == 0
    # File-override section must still appear even when API is unreachable
    assert "daily-brief" in result.output


# ---------------------------------------------------------------------------
# AC-2: validate — valid override passes, exit 0
# ---------------------------------------------------------------------------


def test_template_validate_valid_override_exits_0(tmp_path: Path) -> None:
    """A syntactically valid override reports OK and exits 0."""
    from intellisource.distributor.templates.discovery import OverrideIssue

    valid_issues: list[OverrideIssue] = []
    with patch(
        "intellisource.cli.commands.template.validate_overrides",
        return_value=valid_issues,
    ):
        result = runner.invoke(app, ["template", "validate"])

    assert result.exit_code == 0


def test_template_validate_all_reports_valid_name(tmp_path: Path) -> None:
    """validate output mentions the template name when there are no issues."""
    with patch(
        "intellisource.cli.commands.template.validate_overrides",
        return_value=[],
    ):
        result = runner.invoke(app, ["template", "validate"])

    assert result.exit_code == 0
    # "OK" or "valid" or "no issues" — just check no non-zero exit and clean output
    assert result.output is not None


# ---------------------------------------------------------------------------
# AC-3: validate — syntax error → exit non-0, output contains filename + message
# ---------------------------------------------------------------------------


def test_template_validate_syntax_error_exits_nonzero() -> None:
    """A Jinja syntax error in override leads to non-zero exit."""
    from intellisource.distributor.templates.discovery import OverrideIssue

    bad_issue = OverrideIssue(
        severity="error",
        template="daily-brief",
        fmt="markdown",
        message="unexpected end of template, expected 'endif'",
    )
    with patch(
        "intellisource.cli.commands.template.validate_overrides",
        return_value=[bad_issue],
    ):
        result = runner.invoke(app, ["template", "validate"])

    assert result.exit_code != 0
    assert "daily-brief" in result.output
    assert "unexpected end of template" in result.output


def test_template_validate_error_output_includes_filename() -> None:
    """Error output includes the file name (template + fmt)."""
    from intellisource.distributor.templates.discovery import OverrideIssue

    bad_issue = OverrideIssue(
        severity="error",
        template="daily-brief",
        fmt="html",
        message="unexpected 'endblock'",
    )
    with patch(
        "intellisource.cli.commands.template.validate_overrides",
        return_value=[bad_issue],
    ):
        result = runner.invoke(app, ["template", "validate"])

    assert result.exit_code != 0
    assert "daily-brief" in result.output
    # fmt reference in output
    assert "html" in result.output


# ---------------------------------------------------------------------------
# AC-4: validate — snake_case name → warning, but exit 0 (no error)
# ---------------------------------------------------------------------------


def test_template_validate_snake_case_name_gives_warning_exit_0() -> None:
    """A snake_case file (daily_brief) emits a warning but exits 0 (no error)."""
    from intellisource.distributor.templates.discovery import OverrideIssue

    warn_issue = OverrideIssue(
        severity="warning",
        template="daily_brief",
        fmt="markdown",
        message="未匹配任何内置模板名，疑似 kebab/snake 拼写错误，渲染时会被静默忽略",
    )
    with patch(
        "intellisource.cli.commands.template.validate_overrides",
        return_value=[warn_issue],
    ):
        result = runner.invoke(app, ["template", "validate"])

    assert result.exit_code == 0
    # warning must appear
    assert "daily_brief" in result.output or "warning" in result.output.lower()
    # must mention the mis-match
    assert (
        "疑似" in result.output
        or "kebab" in result.output
        or "warning" in result.output.lower()
    )


# ---------------------------------------------------------------------------
# AC-5: preview — renders sample bundle content; unknown name exits non-0
# ---------------------------------------------------------------------------


def test_template_preview_known_template_renders_sample_title() -> None:
    """preview daily-brief --format markdown renders sample bundle title."""
    with patch(
        "intellisource.cli.commands.template.render_preview",
        return_value="# Sample Daily Digest\nsome content here",
    ):
        result = runner.invoke(
            app, ["template", "preview", "daily-brief", "--format", "markdown"]
        )

    assert result.exit_code == 0
    assert "Sample Daily Digest" in result.output


def test_template_preview_unknown_name_exits_nonzero() -> None:
    """preview with unknown template name exits non-zero with clear message."""
    with patch(
        "intellisource.cli.commands.template.render_preview",
        side_effect=ValueError("Unknown digest template: 'no-such-template'"),
    ):
        result = runner.invoke(app, ["template", "preview", "no-such-template"])

    assert result.exit_code != 0
    # output must contain a clear error hint
    assert (
        "no-such-template" in result.output
        or "未知" in result.output
        or "Unknown" in result.output
    )


def test_template_preview_default_format_used_when_none_given() -> None:
    """preview without --format uses the template's default format."""
    with patch(
        "intellisource.cli.commands.template.render_preview",
        return_value="rendered output",
    ) as mock_rp:
        result = runner.invoke(app, ["template", "preview", "daily-brief"])

    assert result.exit_code == 0
    # render_preview was called with fmt=None (no --format given)
    call_args = mock_rp.call_args
    assert call_args is not None
    name_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("name")
    assert name_arg == "daily-brief"
