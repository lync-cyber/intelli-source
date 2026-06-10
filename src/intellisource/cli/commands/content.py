"""``content`` command group — content-level operations over /api/v1/content."""

from __future__ import annotations

import typer

from intellisource.cli import _client
from intellisource.cli._format import emit

content_app = typer.Typer()


@content_app.command("backfill-embeddings")
def content_backfill_embeddings(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Dispatch the backfill-embeddings task for all content without embeddings."""
    resp = _client.post("/api/v1/content/backfill-embeddings", {})
    if resp.status_code >= 400:
        typer.echo(_client.error_message(resp), err=True)
        raise typer.Exit(1)
    emit(resp.json(), json_output=json_output)
