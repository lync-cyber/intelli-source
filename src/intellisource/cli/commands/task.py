"""``task`` command group — trigger collection + read task status."""

from __future__ import annotations

import typer

from intellisource.cli import _client
from intellisource.cli._format import emit

task_app = typer.Typer()


@task_app.command("trigger")
def task_trigger(
    source_id: str = typer.Argument(..., help="Source ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Trigger a collection task for a source."""
    payload = {"source_ids": [source_id]}
    resp = _client.post("/api/v1/tasks/collect", payload)
    try:
        resp.raise_for_status()
    except Exception:
        detail = ""
        try:
            detail = _client.error_message(resp)
        except Exception:
            pass
        typer.echo(f"Error: {detail or 'not found'}")
        raise typer.Exit(code=1) from None
    emit(resp.json(), json_output=json_output)


@task_app.command("status")
def task_status(
    task_id: str = typer.Argument(..., help="Task ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show task status."""
    resp = _client.get(f"/api/v1/tasks/{task_id}")
    emit(resp.json(), json_output=json_output)
