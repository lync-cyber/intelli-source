"""CLI tool for IntelliSource API interaction."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import typer

app = typer.Typer()
source_app = typer.Typer()
task_app = typer.Typer()
pipeline_app = typer.Typer()

app.add_typer(source_app, name="source")
app.add_typer(task_app, name="task")
app.add_typer(pipeline_app, name="pipeline")


# ---------------------------------------------------------------------------
# Constants & Global state
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "http://localhost:8000"
ENV_API_URL = "IS_API_URL"
ENV_API_KEY = "IS_API_KEY"

_state: dict[str, Any] = {
    "api_url": DEFAULT_API_URL,
    "api_key": "",
}


def _get_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    api_key = _state["api_key"]
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def _base_url() -> str:
    return str(_state["api_url"]).rstrip("/")


def _emit(data: dict[str, Any], *, json_output: bool) -> None:
    """Output *data* as JSON or a human-readable table."""
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(_format_table(data))


def _format_table(data: dict[str, Any] | list[dict[str, Any]]) -> str:
    """Format data as a simple text table."""
    if isinstance(data, dict):
        # If it has 'items', format those
        items: list[dict[str, Any]] = data.get("items", [])
        if not items:
            # Try 'results'
            items = data.get("results", [])
        if not items:
            # Just format the dict itself
            items = [data]
    else:
        items = data

    if not items:
        return "No results."

    # Get all keys from first item
    keys = list(items[0].keys())
    # Build header
    lines: list[str] = []
    header = "  ".join(f"{k:<20}" for k in keys)
    lines.append(header)
    lines.append("-" * len(header))
    for item in items:
        row = "  ".join(f"{str(item.get(k, '')):<20}" for k in keys)
        lines.append(row)
    return "\n".join(lines)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    api_url: str | None = typer.Option(None, "--api-url", help="API base URL"),
    api_key: str | None = typer.Option(None, "--api-key", help="API key"),
) -> None:
    """IntelliSource CLI."""
    if api_url is not None:
        _state["api_url"] = api_url
    else:
        env_url = os.environ.get(ENV_API_URL)
        if env_url:
            _state["api_url"] = env_url

    if api_key is not None:
        _state["api_key"] = api_key
    else:
        env_key = os.environ.get(ENV_API_KEY)
        if env_key:
            _state["api_key"] = env_key

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# source commands
# ---------------------------------------------------------------------------


@source_app.command("list")
def source_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all sources."""
    url = f"{_base_url()}/api/v1/sources"
    resp = httpx.get(url, headers=_get_headers())
    _emit(resp.json(), json_output=json_output)


@source_app.command("add")
def source_add(
    name: str = typer.Option(..., "--name", help="Source name"),
    source_type: str = typer.Option(..., "--type", help="Source type"),
    url: str = typer.Option(..., "--url", help="Source URL"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Add a new source."""
    api_url = f"{_base_url()}/api/v1/sources"
    payload = {"name": name, "type": source_type, "url": url}
    resp = httpx.post(api_url, json=payload, headers=_get_headers())
    _emit(resp.json(), json_output=json_output)


@source_app.command("update")
def source_update(
    source_id: str = typer.Argument(..., help="Source ID"),
    name: str | None = typer.Option(None, "--name", help="New source name"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Update an existing source."""
    url = f"{_base_url()}/api/v1/sources/{source_id}"
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    resp = httpx.patch(url, json=payload, headers=_get_headers())
    _emit(resp.json(), json_output=json_output)


@source_app.command("delete")
def source_delete(
    source_id: str = typer.Argument(..., help="Source ID"),
) -> None:
    """Delete a source."""
    url = f"{_base_url()}/api/v1/sources/{source_id}"
    httpx.delete(url, headers=_get_headers())
    typer.echo("Deleted.")


# ---------------------------------------------------------------------------
# task commands
# ---------------------------------------------------------------------------


@task_app.command("trigger")
def task_trigger(
    source_id: str = typer.Argument(..., help="Source ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Trigger a collection task for a source."""
    url = f"{_base_url()}/api/v1/tasks/collect"
    payload = {"source_ids": [source_id]}
    resp = httpx.post(url, json=payload, headers=_get_headers())
    try:
        resp.raise_for_status()
    except Exception:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            pass
        typer.echo(f"Error: {detail or 'not found'}")
        raise typer.Exit(code=1)
    _emit(resp.json(), json_output=json_output)


@task_app.command("status")
def task_status(
    task_id: str = typer.Argument(..., help="Task ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show task status."""
    url = f"{_base_url()}/api/v1/tasks/{task_id}"
    resp = httpx.get(url, headers=_get_headers())
    _emit(resp.json(), json_output=json_output)


# ---------------------------------------------------------------------------
# pipeline commands
# ---------------------------------------------------------------------------


@pipeline_app.command("list")
def pipeline_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all pipelines."""
    url = f"{_base_url()}/api/v1/pipelines"
    resp = httpx.get(url, headers=_get_headers())
    _emit(resp.json(), json_output=json_output)


# ---------------------------------------------------------------------------
# search command (top-level)
# ---------------------------------------------------------------------------


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Search for content."""
    url = f"{_base_url()}/api/v1/search"
    payload = {"query": query}
    resp = httpx.post(url, json=payload, headers=_get_headers())
    _emit(resp.json(), json_output=json_output)
