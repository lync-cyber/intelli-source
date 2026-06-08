"""``subscriptions`` command group — CRUD + digest render options + reload."""

from __future__ import annotations

import json
from typing import Any

import typer

from intellisource.cli import _client
from intellisource.cli._format import emit, format_detail, format_diff, format_table

subscriptions_app = typer.Typer()

_RENDER_MODE_CHOICES = ("code", "llm-assisted", "llm-freeform")


def _set_digest_fields(
    channel_config: dict[str, Any],
    *,
    template: str | None,
    render_mode: str | None,
    render_budget_chars: int | None,
) -> None:
    """Merge digest template/render fields into *channel_config* in place.

    Validates render_mode (CLI-side, since PATCH bypasses the reload validator)
    and a positive budget; aborts with exit 2 on invalid input.
    """
    if template:
        channel_config["template"] = template
    tmpl_cfg = dict(channel_config.get("template_config") or {})
    if render_mode is not None:
        if render_mode not in _RENDER_MODE_CHOICES:
            typer.echo(
                f"Error: render_mode must be one of {list(_RENDER_MODE_CHOICES)}"
            )
            raise typer.Exit(code=2)
        tmpl_cfg["render_mode"] = render_mode
    if render_budget_chars is not None:
        if render_budget_chars <= 0:
            typer.echo("Error: --render-budget-chars must be a positive integer")
            raise typer.Exit(code=2)
        tmpl_cfg["render_budget_chars"] = render_budget_chars
    if tmpl_cfg:
        channel_config["template_config"] = tmpl_cfg


def _apply_digest_options(
    channel_config: dict[str, Any],
    frequency: str,
    template: str | None,
    render_mode: str | None,
) -> None:
    """Fold digest template / render_mode into channel_config for periodic subs.

    No-op for realtime: per-item push does not read template_config. Prompts
    interactively for render_mode only when the flag is absent and the
    frequency is periodic (daily/weekly).
    """
    if frequency not in ("daily", "weekly"):
        if template or render_mode:
            typer.echo(
                "  note: --template/--render-mode only apply to daily/weekly "
                f"digests; ignored for frequency={frequency!r}"
            )
        return
    if render_mode is None:
        render_mode = typer.prompt(
            "  render_mode (code / llm-assisted / llm-freeform)", default="code"
        )
    _set_digest_fields(
        channel_config,
        template=template,
        render_mode=render_mode,
        render_budget_chars=None,
    )


def _render_mode_annotation(sub: dict[str, Any]) -> str:
    """Explain the configured + effective digest render mode for a subscription."""
    channel_config = sub.get("channel_config") or {}
    tmpl_cfg = channel_config.get("template_config") or {}
    mode = tmpl_cfg.get("render_mode") or (
        "llm-assisted" if tmpl_cfg.get("enhance") else "code"
    )
    template = channel_config.get("template") or "(auto by frequency)"
    frequency = sub.get("frequency")
    lines = [
        "",
        "digest (daily/weekly only):",
        f"  template: {template}",
        f"  render_mode (configured): {mode}",
    ]
    if frequency not in ("daily", "weekly"):
        lines.append(
            f"  note: frequency={frequency} → per-item push; digest fields unused"
        )
    elif mode != "code":
        lines.append(
            "  note: effective mode downgrades to 'code' when the worker lacks the"
            " llm_renderer (freeform) / enhancer (assisted); the mode actually used"
            " is persisted to push_records.render_mode"
        )
    return "\n".join(lines)


def _channel_config_prompt(channel: str) -> dict[str, Any]:
    """Interactive prompt for channel_config keyed off channel type."""
    if channel == "wework":
        user_id = typer.prompt(
            "  channel_config.user_id (企业微信 user_id, | for many, '@all' broadcast)",
            default="@all",
        )
        msg_type = typer.prompt(
            "  channel_config.msg_type (text / markdown / news)", default="text"
        )
        return {"user_id": user_id, "msg_type": msg_type}
    if channel == "email":
        to_addr = typer.prompt("  channel_config.to_addr (recipient email)")
        return {"to_addr": to_addr}
    return {}  # wechat 公众号 has no per-subscription target


@subscriptions_app.command("list")
def subscriptions_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all subscriptions."""
    resp = _client.get("/api/v1/subscriptions")
    emit(resp.json(), json_output=json_output)


@subscriptions_app.command("show")
def subscriptions_show(
    sub_id: str = typer.Argument(..., help="Subscription id (uuid)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show one subscription's full config + the effective digest render mode."""
    resp = _client.get(f"/api/v1/subscriptions/{sub_id}")
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(format_detail(data))
        typer.echo(_render_mode_annotation(data))


@subscriptions_app.command("add")
def subscriptions_add(
    name: str = typer.Option(None, "--name", help="Subscription name"),
    channel: str = typer.Option(None, "--channel", help="wework / wechat / email"),
    tags: str = typer.Option(
        "", "--tags", help="Comma-separated match_rules.tags (e.g. 'ai,security')"
    ),
    frequency: str = typer.Option("realtime", "--frequency", help="realtime/daily/..."),
    template: str = typer.Option(
        None,
        "--template",
        help="Digest template (daily/weekly only): daily-brief|weekly-roundup|"
        "topic-deepdive|json-feed. Omit = auto by frequency.",
    ),
    render_mode: str = typer.Option(
        None,
        "--render-mode",
        help="Digest render (daily/weekly only): code|llm-assisted|llm-freeform.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Interactively create a subscription. Falls back to prompts for missing flags."""
    if not name:
        name = typer.prompt("Subscription name")
    if not channel:
        channel = typer.prompt("Channel (wework / wechat / email)", default="wework")
    if channel not in {"wework", "wechat", "email"}:
        typer.echo(f"Error: channel must be wework/wechat/email, got {channel!r}")
        raise typer.Exit(code=2)

    channel_config = _channel_config_prompt(channel)
    _apply_digest_options(channel_config, frequency, template, render_mode)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    if not tag_list:
        prompt_tags = typer.prompt(
            "match_rules.tags (comma-separated, blank for none)", default=""
        )
        tag_list = [t.strip() for t in prompt_tags.split(",") if t.strip()]

    payload: dict[str, Any] = {
        "name": name,
        "channel": channel,
        "channel_config": channel_config,
        "match_rules": {"tags": tag_list} if tag_list else {},
        "frequency": frequency,
    }
    resp = _client.post_json("/api/v1/subscriptions", payload)
    if resp.status_code >= 400:
        try:
            detail = _client.error_message(resp)
        except Exception:
            detail = resp.text
        typer.echo(f"Error ({resp.status_code}): {detail}")
        raise typer.Exit(code=1)
    emit(resp.json(), json_output=json_output)


@subscriptions_app.command("patch")
def subscriptions_patch(
    sub_id: str = typer.Argument(..., help="Subscription id (uuid)"),
    name: str | None = typer.Option(None, "--name"),
    frequency: str | None = typer.Option(None, "--frequency"),
    status: str | None = typer.Option(None, "--status", help="active / paused"),
    template: str | None = typer.Option(
        None, "--template", help="Digest template (daily/weekly only)"
    ),
    render_mode: str | None = typer.Option(
        None, "--render-mode", help="code|llm-assisted|llm-freeform (daily/weekly only)"
    ),
    render_budget_chars: int | None = typer.Option(
        None, "--render-budget-chars", help="LLM input budget (llm-freeform only)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Partial-update a subscription by id.

    Digest fields (--template/--render-mode/--render-budget-chars) merge into
    the existing channel_config — fetched first so other keys (to_addr etc.)
    survive — since PATCH replaces channel_config wholesale.
    """
    path = f"/api/v1/subscriptions/{sub_id}"
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if frequency is not None:
        body["frequency"] = frequency
    if status is not None:
        body["status"] = status

    if (
        template is not None
        or render_mode is not None
        or render_budget_chars is not None
    ):
        current = _client.get(path)
        if current.status_code == 404:
            typer.echo("Not found")
            raise typer.Exit(code=1)
        channel_config = dict(current.json().get("channel_config") or {})
        _set_digest_fields(
            channel_config,
            template=template,
            render_mode=render_mode,
            render_budget_chars=render_budget_chars,
        )
        body["channel_config"] = channel_config

    if not body:
        typer.echo(
            "Nothing to patch — pass at least one of --name/--frequency/--status/"
            "--template/--render-mode/--render-budget-chars"
        )
        raise typer.Exit(code=2)
    resp = _client.patch(path, body)
    if resp.status_code >= 400:
        typer.echo(f"Error ({resp.status_code}): {resp.text}")
        raise typer.Exit(code=1)
    emit(resp.json(), json_output=json_output)


@subscriptions_app.command("rm")
def subscriptions_rm(
    sub_id: str = typer.Argument(..., help="Subscription id (uuid)"),
) -> None:
    """Soft-delete (paused) a subscription by id."""
    resp = _client.delete(f"/api/v1/subscriptions/{sub_id}")
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    typer.echo("Paused.")


@subscriptions_app.command("reload")
def subscriptions_reload(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Reload all subscriptions from yaml (records a new version snapshot)."""
    resp = _client.post_json("/api/v1/subscriptions/reload", {})
    emit(resp.json(), json_output=json_output)


@subscriptions_app.command("rollback")
def subscriptions_rollback(
    version: str = typer.Argument(..., help="Version label to rollback to (e.g. '1')"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Rollback subscriptions to a previously recorded version snapshot."""
    resp = _client.post_json(f"/api/v1/subscriptions/config/rollback/{version}", {})
    if resp.status_code == 404:
        typer.echo(f"Version {version!r} not found")
        raise typer.Exit(code=1)
    emit(resp.json(), json_output=json_output)


@subscriptions_app.command("versions")
def subscriptions_versions(
    limit: int = typer.Option(20, "--limit", help="Max versions to list"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List recorded subscription config version snapshots (for rollback)."""
    resp = _client.get(f"/api/v1/subscriptions/config/versions?limit={limit}")
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(format_table({"items": data.get("versions", [])}))


@subscriptions_app.command("diff")
def subscriptions_diff(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Diff the subscriptions yaml SSOT against DB state (reload preview)."""
    resp = _client.get("/api/v1/subscriptions/config/diff")
    if resp.status_code >= 400:
        typer.echo(f"Error ({resp.status_code}): {resp.text}")
        raise typer.Exit(code=1)
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(format_diff(data))
