"""``template`` command group — custom digest template CRUD."""

from __future__ import annotations

from typing import Any

import typer

from intellisource.cli import _client
from intellisource.cli._format import emit
from intellisource.distributor.templates.discovery import (
    list_file_overrides,
    render_preview,
    validate_overrides,
)

template_app = typer.Typer()


@template_app.command("list")
def template_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List digest templates (built-in + custom)."""
    api_ok = True
    try:
        resp = _client.get("/api/v1/templates")
        emit(resp.json(), json_output=json_output)
    except typer.Exit:
        typer.echo("（服务不可达，仅显示本地文件覆盖）")
        api_ok = False

    overrides = list_file_overrides()
    typer.echo("\n文件覆盖（config/templates/）：")
    if overrides:
        for name, formats in sorted(overrides.items()):
            typer.echo(f"  {name}: {', '.join(formats)}")
    else:
        typer.echo("  无")

    if not api_ok:
        raise typer.Exit(code=0)


@template_app.command("show")
def template_show(
    name: str = typer.Argument(..., help="Template name"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show a template's detail by name (built-in or custom)."""
    resp = _client.get(f"/api/v1/templates/{name}")
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    emit(resp.json(), json_output=json_output)


@template_app.command("add")
def template_add(
    name: str = typer.Option(..., "--name", help="Template name"),
    base_template: str = typer.Option(
        ..., "--base", help="Built-in base template (e.g. daily-brief, push-card)"
    ),
    formats: str = typer.Option(
        ..., "--formats", help="Comma-separated formats (e.g. markdown,text)"
    ),
    default_format: str = typer.Option(..., "--default-format", help="Default format"),
    source: str | None = typer.Option(
        None, "--source", help="Jinja source applied to the default format"
    ),
    title: str | None = typer.Option(
        None, "--title", help="aggregate_config.title override"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Create or replace a custom digest template."""
    fmt_list = [f.strip() for f in formats.split(",") if f.strip()]
    jinja_source: dict[str, str] = {}
    if source is not None:
        jinja_source[default_format] = source
    aggregate_config: dict[str, Any] = {}
    if title is not None:
        aggregate_config["title"] = title
    payload: dict[str, Any] = {
        "name": name,
        "base_template": base_template,
        "formats": fmt_list,
        "default_format": default_format,
        "jinja_source": jinja_source,
        "aggregate_config": aggregate_config,
    }
    resp = _client.post_json("/api/v1/templates", payload)
    if resp.status_code >= 400:
        try:
            detail = _client.error_message(resp)
        except Exception:
            detail = resp.text
        typer.echo(f"Error ({resp.status_code}): {detail}")
        raise typer.Exit(code=1)
    emit(resp.json(), json_output=json_output)


@template_app.command("rm")
def template_rm(
    name: str = typer.Argument(..., help="Template name"),
) -> None:
    """Delete a custom template by name."""
    resp = _client.delete(f"/api/v1/templates/{name}")
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    typer.echo("Deleted.")


@template_app.command("validate")
def template_validate(
    name: str | None = typer.Argument(
        None, help="Template name to validate (omit for all overrides)"
    ),
) -> None:
    """Validate file override templates in config/templates/."""
    issues = validate_overrides(only=name)

    if not issues:
        typer.echo("All overrides are valid.")
        return

    has_error = False
    for issue in issues:
        prefix = "ERROR" if issue.severity == "error" else "WARNING"
        typer.echo(f"[{prefix}] {issue.template}.{issue.fmt}.j2: {issue.message}")
        if issue.severity == "error":
            has_error = True

    if has_error:
        raise typer.Exit(code=1)


@template_app.command("preview")
def template_preview(
    name: str = typer.Argument(..., help="Template name to preview"),
    fmt: str | None = typer.Option(
        None, "--format", "-f", help="Output format (defaults to template's default)"
    ),
) -> None:
    """Render a preview of a template using a sample bundle."""
    try:
        output = render_preview(name, fmt)
    except ValueError as exc:
        typer.echo(f"未知模板: {name!r} — {exc}")
        raise typer.Exit(code=1) from None
    typer.echo(output)
