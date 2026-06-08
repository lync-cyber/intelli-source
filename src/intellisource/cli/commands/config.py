"""``config`` command group — aggregate yaml↔DB drift across config domains."""

from __future__ import annotations

import json
from typing import Any

import typer

from intellisource.cli import _client
from intellisource.cli._format import format_diff

config_app = typer.Typer()


def _domain_config_status(domain: str) -> dict[str, Any]:
    """Fetch yaml↔DB diff + latest recorded version for one config *domain*.

    *domain* is ``"sources"`` or ``"subscriptions"``. Errors are folded into the
    returned dict (never raised) so one domain failing does not hide the other.
    """
    diff_resp = _client.get(f"/api/v1/{domain}/config/diff")
    versions_resp = _client.get(f"/api/v1/{domain}/config/versions?limit=1")
    diff: dict[str, Any]
    if diff_resp.status_code >= 400:
        diff = {"error": diff_resp.text}
    else:
        diff = diff_resp.json()
    versions = (
        versions_resp.json().get("versions", [])
        if versions_resp.status_code < 400
        else []
    )
    latest = versions[0]["version"] if versions else None
    return {"diff": diff, "latest_version": latest}


@config_app.command("status")
def config_status(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Aggregate yaml↔DB drift + latest version for sources and subscriptions.

    One reload preview across both config domains: what a reload would CREATE /
    UPDATE, and (per domain) whether db-only entries are PAUSED (subscriptions,
    full sync) or PRESERVED (sources, additive upsert).
    """
    result = {d: _domain_config_status(d) for d in ("sources", "subscriptions")}
    if json_output:
        typer.echo(json.dumps(result))
        return
    for domain in ("sources", "subscriptions"):
        info = result[domain]
        typer.echo(f"== {domain} (yaml ↔ DB) ==")
        typer.echo(f"latest recorded version: {info['latest_version'] or '(none)'}")
        diff = info["diff"]
        if "error" in diff:
            typer.echo(f"  diff unavailable: {diff['error']}")
        else:
            typer.echo(format_diff(diff))
        typer.echo("")
