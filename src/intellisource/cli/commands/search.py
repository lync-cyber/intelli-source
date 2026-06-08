"""Top-level ``search`` command — query collected content."""

from __future__ import annotations

import typer

from intellisource.cli import _client
from intellisource.cli._format import emit


def search(
    query: str = typer.Argument(..., help="Search query"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Search for content."""
    resp = _client.post("/api/v1/search", {"query": query})
    emit(resp.json(), json_output=json_output)


def register(app: typer.Typer) -> None:
    """Attach the ``search`` command to the root *app*."""
    app.command("search")(search)
