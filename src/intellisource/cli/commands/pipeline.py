"""``pipeline`` command group — CRUD + run over /api/v1/pipelines."""

from __future__ import annotations

import json
from typing import Any

import typer

from intellisource.cli import _client
from intellisource.cli._format import emit, format_detail

pipeline_app = typer.Typer()


@pipeline_app.command("list")
def pipeline_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all pipelines."""
    resp = _client.get("/api/v1/pipelines")
    emit(resp.json(), json_output=json_output)


@pipeline_app.command("show")
def pipeline_show(
    name: str = typer.Argument(..., help="Pipeline name"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show a single pipeline's full definition (vertical detail view)."""
    resp = _client.get(f"/api/v1/pipelines/{name}")
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(format_detail(data))


@pipeline_app.command("run")
def pipeline_run(
    name: str = typer.Argument(..., help="Pipeline name"),
    params: str | None = typer.Option(
        None, "--params", help="JSON object of run params (e.g. '{\"limit\": 10}')"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Trigger a run of the named pipeline (returns task + task_chain ids)."""
    payload: dict[str, Any] = {}
    if params is not None:
        try:
            payload["params"] = json.loads(params)
        except json.JSONDecodeError as exc:
            typer.echo(f"Error: --params must be valid JSON ({exc})")
            raise typer.Exit(code=2) from None
    resp = _client.post_json(f"/api/v1/pipelines/{name}/run", payload)
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    if resp.status_code >= 400:
        try:
            detail = _client.error_message(resp)
        except Exception:
            detail = resp.text
        typer.echo(f"Error ({resp.status_code}): {detail}")
        raise typer.Exit(code=1)
    emit(resp.json(), json_output=json_output)


@pipeline_app.command("create")
def pipeline_create(
    name: str = typer.Option(..., "--name", help="Pipeline name"),
    mode: str = typer.Option("flexible", "--mode", help="strict / flexible / batch"),
    steps: str = typer.Option(
        "[]", "--steps", help='JSON array of step objects (e.g. \'[{"tool": "x"}]\')'
    ),
    max_steps: int = typer.Option(50, "--max-steps", help="Max execution steps"),
    on_failure: str = typer.Option(
        "abort", "--on-failure", help="abort / skip / retry (strict mode only)"
    ),
    tools_allowed: str = typer.Option(
        "", "--tools-allowed", help="Comma-separated allowed tool names"
    ),
    tools_denied: str = typer.Option(
        "", "--tools-denied", help="Comma-separated denied tool names"
    ),
    agent_mode: str = typer.Option(
        "process", "--agent-mode", help="process / analyze / preview"
    ),
    system_prompt: str | None = typer.Option(
        None, "--system-prompt", help="System prompt override"
    ),
    max_tokens_budget: int | None = typer.Option(
        None, "--max-tokens-budget", help="Token budget cap"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Create or replace a pipeline definition (idempotent upsert by name)."""
    try:
        step_list = json.loads(steps)
    except json.JSONDecodeError as exc:
        typer.echo(f"Error: --steps must be valid JSON ({exc})")
        raise typer.Exit(code=2) from None
    payload: dict[str, Any] = {
        "name": name,
        "mode": mode,
        "steps": step_list,
        "max_steps": max_steps,
        "on_failure": on_failure,
        "tools_allowed": [t.strip() for t in tools_allowed.split(",") if t.strip()],
        "tools_denied": [t.strip() for t in tools_denied.split(",") if t.strip()],
        "agent_mode": agent_mode,
    }
    if system_prompt is not None:
        payload["system_prompt"] = system_prompt
    if max_tokens_budget is not None:
        payload["max_tokens_budget"] = max_tokens_budget
    resp = _client.post_json("/api/v1/pipelines", payload)
    if resp.status_code >= 400:
        try:
            detail = _client.error_message(resp)
        except Exception:
            detail = resp.text
        typer.echo(f"Error ({resp.status_code}): {detail}")
        raise typer.Exit(code=1)
    emit(resp.json(), json_output=json_output)


@pipeline_app.command("update")
def pipeline_update(
    name: str = typer.Argument(..., help="Pipeline name"),
    mode: str | None = typer.Option(None, "--mode", help="strict / flexible / batch"),
    steps: str | None = typer.Option(
        None, "--steps", help="JSON array of step objects (replaces existing)"
    ),
    max_steps: int | None = typer.Option(None, "--max-steps", help="Max steps"),
    on_failure: str | None = typer.Option(
        None, "--on-failure", help="abort / skip / retry"
    ),
    tools_allowed: str | None = typer.Option(
        None,
        "--tools-allowed",
        help="Comma-separated allowed tools (replaces existing)",
    ),
    tools_denied: str | None = typer.Option(
        None, "--tools-denied", help="Comma-separated denied tools (replaces existing)"
    ),
    agent_mode: str | None = typer.Option(
        None, "--agent-mode", help="process / analyze / preview"
    ),
    system_prompt: str | None = typer.Option(
        None, "--system-prompt", help="System prompt override"
    ),
    max_tokens_budget: int | None = typer.Option(
        None, "--max-tokens-budget", help="Token budget cap"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Update an existing pipeline (partial — only passed fields change)."""
    payload: dict[str, Any] = {}
    if mode is not None:
        payload["mode"] = mode
    if steps is not None:
        try:
            payload["steps"] = json.loads(steps)
        except json.JSONDecodeError as exc:
            typer.echo(f"Error: --steps must be valid JSON ({exc})")
            raise typer.Exit(code=2) from None
    if max_steps is not None:
        payload["max_steps"] = max_steps
    if on_failure is not None:
        payload["on_failure"] = on_failure
    if tools_allowed is not None:
        payload["tools_allowed"] = [
            t.strip() for t in tools_allowed.split(",") if t.strip()
        ]
    if tools_denied is not None:
        payload["tools_denied"] = [
            t.strip() for t in tools_denied.split(",") if t.strip()
        ]
    if agent_mode is not None:
        payload["agent_mode"] = agent_mode
    if system_prompt is not None:
        payload["system_prompt"] = system_prompt
    if max_tokens_budget is not None:
        payload["max_tokens_budget"] = max_tokens_budget
    if not payload:
        typer.echo(
            "Nothing to update — pass at least one of --mode/--steps/--max-steps/"
            "--on-failure/--tools-allowed/--tools-denied/--agent-mode/"
            "--system-prompt/--max-tokens-budget"
        )
        raise typer.Exit(code=2)
    resp = _client.patch(f"/api/v1/pipelines/{name}", payload)
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    if resp.status_code >= 400:
        typer.echo(f"Error ({resp.status_code}): {resp.text}")
        raise typer.Exit(code=1)
    emit(resp.json(), json_output=json_output)


@pipeline_app.command("rm")
def pipeline_rm(
    name: str = typer.Argument(..., help="Pipeline name"),
) -> None:
    """Delete a pipeline definition by name."""
    resp = _client.delete(f"/api/v1/pipelines/{name}")
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    typer.echo("Deleted.")
