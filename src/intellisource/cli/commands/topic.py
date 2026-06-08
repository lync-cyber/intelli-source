"""``topic`` command group — list / show / enable built-in collection topics."""

from __future__ import annotations

import json
from typing import Any

import typer

from intellisource.cli import _client
from intellisource.cli._format import emit, format_detail

topic_app = typer.Typer()


@topic_app.command("list")
def topic_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List the built-in collection topics (discipline / industry packs)."""
    resp = _client.get("/api/v1/topics")
    emit(resp.json(), json_output=json_output)


@topic_app.command("show")
def topic_show(
    topic_id: str = typer.Argument(..., help="Topic id, e.g. artificial-intelligence"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show a single topic's full detail (sources + subscription template)."""
    resp = _client.get(f"/api/v1/topics/{topic_id}")
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(format_detail(data))


@topic_app.command("enable")
def topic_enable(
    topic_id: str = typer.Argument(..., help="Topic id, e.g. artificial-intelligence"),
    channel: str | None = typer.Option(
        None, "--channel", help="wework / wechat / email — also creates a subscription"
    ),
    to_addr: str | None = typer.Option(None, "--to-addr", help="email recipient"),
    user_id: str | None = typer.Option(None, "--user-id", help="wework user id"),
    no_subscription: bool = typer.Option(
        False, "--no-subscription", help="Only import sources, skip subscription"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Provision a topic: import its sources and (optionally) subscribe a channel."""
    if channel is not None and channel not in {"wework", "wechat", "email"}:
        typer.echo(f"Error: channel must be wework/wechat/email, got {channel!r}")
        raise typer.Exit(code=2)

    channel_config: dict[str, Any] = {}
    if channel == "email" and to_addr:
        channel_config["to_addr"] = to_addr
    if channel == "wework" and user_id:
        channel_config["user_id"] = user_id

    payload: dict[str, Any] = {
        "channel": channel,
        "channel_config": channel_config,
        "create_subscription": not no_subscription,
    }
    resp = _client.post_json(f"/api/v1/topics/{topic_id}/enable", payload)
    if resp.status_code == 404:
        typer.echo(f"Topic {topic_id!r} not found")
        raise typer.Exit(code=1)
    if resp.status_code >= 400:
        try:
            detail = _client.error_message(resp)
        except Exception:
            detail = resp.text
        typer.echo(f"Error ({resp.status_code}): {detail}")
        raise typer.Exit(code=1)
    emit(resp.json(), json_output=json_output)
