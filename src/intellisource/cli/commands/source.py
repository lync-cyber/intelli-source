"""``source`` command group — CRUD + config version/diff over /api/v1/sources."""

from __future__ import annotations

import json
from typing import Any

import typer

from intellisource.cli import _client
from intellisource.cli._format import emit, format_detail, format_diff, format_table

source_app = typer.Typer()


@source_app.command("list")
def source_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all sources."""
    resp = _client.get("/api/v1/sources")
    emit(resp.json(), json_output=json_output)


@source_app.command("show")
def source_show(
    source_id: str = typer.Argument(..., help="Source ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show a single source's full config (vertical detail view)."""
    resp = _client.get(f"/api/v1/sources/{source_id}")
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(format_detail(data))


@source_app.command("add")
def source_add(
    name: str = typer.Option(..., "--name", help="Source name"),
    source_type: str = typer.Option(..., "--type", help="Source type"),
    url: str = typer.Option(..., "--url", help="Source URL"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Add a new source."""
    payload = {"name": name, "type": source_type, "url": url}
    resp = _client.post("/api/v1/sources", payload)
    emit(resp.json(), json_output=json_output)


@source_app.command("update")
def source_update(
    source_id: str = typer.Argument(..., help="Source ID"),
    name: str | None = typer.Option(None, "--name", help="New source name"),
    url: str | None = typer.Option(None, "--url", help="New source URL"),
    source_type: str | None = typer.Option(None, "--type", help="New source type"),
    tags: str | None = typer.Option(
        None, "--tags", help="Comma-separated tags (replaces existing)"
    ),
    schedule_interval: int | None = typer.Option(
        None, "--schedule-interval", help="Collection interval (seconds)"
    ),
    status: str | None = typer.Option(None, "--status", help="active / paused"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Update an existing source (partial — only passed fields change)."""
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if url is not None:
        payload["url"] = url
    if source_type is not None:
        payload["type"] = source_type
    if tags is not None:
        payload["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    if schedule_interval is not None:
        payload["schedule_interval"] = schedule_interval
    if status is not None:
        payload["status"] = status
    if not payload:
        typer.echo(
            "Nothing to update — pass at least one of "
            "--name/--url/--type/--tags/--schedule-interval/--status"
        )
        raise typer.Exit(code=2)
    resp = _client.patch(f"/api/v1/sources/{source_id}", payload)
    if resp.status_code >= 400:
        typer.echo(f"Error ({resp.status_code}): {resp.text}")
        raise typer.Exit(code=1)
    emit(resp.json(), json_output=json_output)


@source_app.command("delete")
def source_delete(
    source_id: str = typer.Argument(..., help="Source ID"),
) -> None:
    """Delete a source."""
    _client.delete(f"/api/v1/sources/{source_id}")
    typer.echo("Deleted.")


@source_app.command("versions")
def source_versions(
    limit: int = typer.Option(20, "--limit", help="Max versions to list"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List recorded source config version snapshots (for rollback)."""
    resp = _client.get(f"/api/v1/sources/config/versions?limit={limit}")
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(format_table({"items": data.get("versions", [])}))


@source_app.command("diff")
def source_diff(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Diff the sources yaml SSOT against current DB state (reload preview)."""
    resp = _client.get("/api/v1/sources/config/diff")
    if resp.status_code >= 400:
        typer.echo(f"Error ({resp.status_code}): {resp.text}")
        raise typer.Exit(code=1)
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(format_diff(data))
