"""CLI tool for IntelliSource API interaction."""

from __future__ import annotations

import json
import os
import pathlib
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


# ---------------------------------------------------------------------------
# doctor command (Phase C — config self-check)
# ---------------------------------------------------------------------------

_API_KEY_PLACEHOLDER = "change-me-in-production"

_REQUIRED_CHANNEL_VARS: list[tuple[str, list[str]]] = [
    ("wework", ["IS_WEWORK_CORP_ID", "IS_WEWORK_CORP_SECRET", "IS_WEWORK_AGENT_ID"]),
    ("wechat", ["IS_WECHAT_APP_ID", "IS_WECHAT_APP_SECRET"]),
    ("email", ["IS_SMTP_HOST", "IS_SMTP_USER", "IS_SMTP_PASSWORD"]),
]

_LLM_KEYS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "AZURE_API_KEY"]


def _load_dotenv_file(path: str) -> dict[str, str]:
    """Parse a .env file into a dict; skip comments and blank lines."""
    result: dict[str, str] = {}
    p = pathlib.Path(path)
    if not p.exists():
        return result
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _doctor_env(env: dict[str, str]) -> list[tuple[str, bool, str]]:
    """Return list of (label, ok, message) for each check."""
    items: list[tuple[str, bool, str]] = []

    api_key = env.get("IS_API_KEY", "")
    if api_key == _API_KEY_PLACEHOLDER:
        items.append(("IS_API_KEY", False, "default placeholder — change before use"))
    elif not api_key:
        items.append(("IS_API_KEY", False, "not set"))
    else:
        items.append(("IS_API_KEY", True, "set"))

    for var in ["IS_DATABASE_URL", "IS_REDIS_URL", "IS_CELERY_BROKER_URL"]:
        val = env.get(var, "")
        items.append((var, bool(val), "set" if val else "not set"))

    llm_key = next((k for k in _LLM_KEYS if env.get(k)), None)
    if llm_key:
        items.append(("LLM key", True, f"{llm_key} set"))
    else:
        items.append(("LLM key", False, f"none of {', '.join(_LLM_KEYS)} set"))

    src_dir = env.get("IS_SOURCE_CONFIG_DIR", "config/sources")
    if not pathlib.Path(src_dir).is_dir():
        items.append((f"sources dir ({src_dir})", False, "directory missing"))
    else:
        yamls = [
            f
            for f in pathlib.Path(src_dir).iterdir()
            if f.suffix in (".yaml", ".yml") and f.is_file()
        ]
        if yamls:
            items.append(
                (f"sources dir ({src_dir})", True, f"{len(yamls)} YAML file(s)")
            )
        else:
            items.append((f"sources dir ({src_dir})", False, "no YAML files found"))

    for channel, vars_ in _REQUIRED_CHANNEL_VARS:
        missing = [v for v in vars_ if not env.get(v)]
        if missing:
            items.append(
                (
                    f"channel {channel}",
                    None,  # type: ignore[arg-type]
                    f"optional — {', '.join(missing)} not set",
                )
            )
        else:
            items.append((f"channel {channel}", True, "configured"))

    return items


@app.command("doctor")
def doctor(
    env_file: str = typer.Option(
        "docker/.env", "--env-file", help=".env file to inspect"
    ),
    check_api: bool = typer.Option(
        False, "--check-api", help="Try to reach the running API"
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Exit 1 if any required item missing"
    ),
) -> None:
    """Check configuration and report missing or misconfigured items."""
    env = {**_load_dotenv_file(env_file), **os.environ}

    items = _doctor_env(env)
    errors = 0
    for label, ok, msg in items:
        if ok is True:
            typer.echo(f"  ✓  {label:<35} {msg}")
        elif ok is False:
            typer.echo(f"  ✗  {label:<35} {msg}", err=False)
            errors += 1
        else:
            typer.echo(f"  ○  {label:<35} {msg}")

    if check_api:
        try:
            resp = httpx.get(f"{_base_url()}/health", timeout=3)
            status = resp.json().get("status", "unknown")
            typer.echo(f"  ✓  API /health                        {status}")
            missing = resp.json().get("missing_config", [])
            for w in missing:
                typer.echo(f"  ○  API warning                        {w}")
        except Exception as exc:
            typer.echo(f"  ✗  API /health                        unreachable ({exc})")
            errors += 1

    if errors:
        typer.echo(f"\n{errors} required item(s) need attention.")
        if strict:
            raise typer.Exit(code=1)
    else:
        typer.echo("\nAll required items OK.")


# ---------------------------------------------------------------------------
# init command (Phase A — interactive first-time setup)
# ---------------------------------------------------------------------------

_DEFAULT_HN_SOURCE = """\
- name: Hacker News
  type: rss
  url: https://news.ycombinator.com/rss
  schedule_interval: 1800
  tags: [tech, news]
"""

_PROVIDER_ENV: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _write_env_file(path: pathlib.Path, updates: dict[str, str]) -> None:
    """Merge ``updates`` into an existing .env file (or create from .env.example)."""
    example = pathlib.Path("docker/.env.example")
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    elif example.exists():
        lines = example.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    written: set[str] = set()
    out: list[str] = []
    for raw in lines:
        key = raw.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            out.append(raw)

    for key, val in updates.items():
        if key not in written:
            out.append(f"{key}={val}")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")


@app.command("init")
def init(
    env_file: str = typer.Option(
        "docker/.env", "--env-file", help="Path to write .env"
    ),
    sources_file: str = typer.Option(
        "config/sources/sources.yaml",
        "--sources-file",
        help="Path to write sources YAML",
    ),
) -> None:
    """Interactive first-time setup: generate .env and a starter sources file."""
    typer.echo("Welcome to IntelliSource setup.\n")

    env_path = pathlib.Path(env_file)
    sources_path = pathlib.Path(sources_file)

    # --- API key ---
    api_key = typer.prompt(
        "API key for IntelliSource (leave blank to auto-generate)",
        default="",
    )
    if not api_key:
        import secrets

        api_key = secrets.token_hex(32)
        typer.echo(f"Generated: {api_key}")

    # --- LLM provider ---
    typer.echo("\nLLM provider:")
    typer.echo("  1. DeepSeek  (recommended — low cost)")
    typer.echo("  2. OpenAI")
    typer.echo("  3. Anthropic")
    provider_choice = typer.prompt("Choose (1/2/3)", default="1")
    provider_map = {"1": "deepseek", "2": "openai", "3": "anthropic"}
    provider = provider_map.get(provider_choice, "deepseek")
    llm_key_var = _PROVIDER_ENV[provider]
    llm_key_val = typer.prompt(f"{llm_key_var}")

    # --- Distribution channel ---
    typer.echo("\nDistribution channel (optional — can add later):")
    typer.echo("  1. WeWork / 企业微信  (recommended)")
    typer.echo("  2. WeChat Official Account")
    typer.echo("  3. Email SMTP")
    typer.echo("  4. Skip for now")
    ch_choice = typer.prompt("Choose (1/2/3/4)", default="4")

    channel_updates: dict[str, str] = {}
    if ch_choice == "1":
        channel_updates["IS_WEWORK_CORP_ID"] = typer.prompt("IS_WEWORK_CORP_ID")
        channel_updates["IS_WEWORK_CORP_SECRET"] = typer.prompt("IS_WEWORK_CORP_SECRET")
        channel_updates["IS_WEWORK_AGENT_ID"] = typer.prompt("IS_WEWORK_AGENT_ID")
        channel_updates["IS_WEWORK_WEBHOOK_TOKEN"] = typer.prompt(
            "IS_WEWORK_WEBHOOK_TOKEN (for incoming webhook verification)", default=""
        )
    elif ch_choice == "2":
        channel_updates["IS_WECHAT_APP_ID"] = typer.prompt("IS_WECHAT_APP_ID")
        channel_updates["IS_WECHAT_APP_SECRET"] = typer.prompt("IS_WECHAT_APP_SECRET")
        channel_updates["IS_WECHAT_WEBHOOK_TOKEN"] = typer.prompt(
            "IS_WECHAT_WEBHOOK_TOKEN", default=""
        )
    elif ch_choice == "3":
        channel_updates["IS_SMTP_HOST"] = typer.prompt("IS_SMTP_HOST")
        channel_updates["IS_SMTP_USER"] = typer.prompt("IS_SMTP_USER")
        channel_updates["IS_SMTP_PASSWORD"] = typer.prompt(
            "IS_SMTP_PASSWORD", hide_input=True
        )
        channel_updates["IS_SMTP_PORT"] = typer.prompt("IS_SMTP_PORT", default="587")
        channel_updates["IS_SMTP_USE_TLS"] = typer.prompt(
            "IS_SMTP_USE_TLS (true/false)", default="true"
        )

    # --- Starter RSS source ---
    add_hn = typer.confirm("\nAdd Hacker News RSS as a starter source?", default=True)

    # --- Write files ---
    env_path.parent.mkdir(parents=True, exist_ok=True)
    updates: dict[str, str] = {"IS_API_KEY": api_key, llm_key_var: llm_key_val}
    updates.update(channel_updates)
    _write_env_file(env_path, updates)
    typer.echo(f"\n✓ Written {env_path}")

    if add_hn:
        sources_path.parent.mkdir(parents=True, exist_ok=True)
        if not sources_path.exists():
            sources_path.write_text(_DEFAULT_HN_SOURCE, encoding="utf-8")
            typer.echo(f"✓ Written {sources_path}")
        else:
            typer.echo(f"  {sources_path} already exists — skipped")

    typer.echo("\nNext steps:")
    typer.echo("  make up")
    typer.echo("  uv run intellisource doctor --check-api")
