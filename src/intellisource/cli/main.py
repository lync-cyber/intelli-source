"""CLI tool for IntelliSource API interaction."""

from __future__ import annotations

import json
import os
import pathlib
import secrets
import subprocess
import time
from collections.abc import Callable
from typing import Any

import httpx
import typer

from intellisource.core.encoding import (
    enforce_utf8_runtime,
    read_text,
    reexec_in_utf8_mode_if_needed,
    write_text,
)
from intellisource.core.paths import project_root
from intellisource.core.settings import (
    PROVIDER_ENV_KEYS,
    get_settings,
    load_provider_env,
)

app = typer.Typer()
source_app = typer.Typer()
task_app = typer.Typer()
pipeline_app = typer.Typer()
subscriptions_app = typer.Typer()
topic_app = typer.Typer()
config_app = typer.Typer()
template_app = typer.Typer()

app.add_typer(source_app, name="source")
app.add_typer(task_app, name="task")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(subscriptions_app, name="subscriptions")
app.add_typer(topic_app, name="topic")
app.add_typer(config_app, name="config")
app.add_typer(template_app, name="template")


def run() -> None:
    """Console-script entrypoint: enter UTF-8 mode (re-exec if needed) then dispatch.

    Runs before typer parses argv so help text and parse errors are emitted in
    UTF-8 too. Tests drive ``app`` directly via ``CliRunner`` and never hit this,
    so the re-exec can only fire on a genuine standalone launch.
    """
    reexec_in_utf8_mode_if_needed()
    app()


# ---------------------------------------------------------------------------
# Constants & Global state
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "http://localhost:8000"

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


def _http(call: Callable[[], httpx.Response]) -> httpx.Response:
    """Run an httpx call; turn a connection failure into a friendly CLI exit.

    The underlying ``httpx.<method>`` call is left intact (so tests that patch
    it still observe the call) — only the raw ConnectError traceback a newcomer
    hits when the API is not running gets replaced with a clear hint.
    """
    try:
        return call()
    except httpx.ConnectError:
        typer.echo(
            "Error: cannot reach the API — is it running?\n"
            "  Start it with: uv run intellisource up"
        )
        raise typer.Exit(code=1) from None


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


def _format_detail(data: dict[str, Any]) -> str:
    """Vertical ``key: value`` view; nested dict/list rendered indented JSON."""
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, (dict, list)) and value:
            lines.append(f"{key}:")
            rendered = json.dumps(value, ensure_ascii=False, indent=2)
            lines.extend(f"  {rline}" for rline in rendered.splitlines())
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _format_diff(data: dict[str, Any]) -> str:
    """Render a yaml↔DB config diff (what a reload would change)."""
    action = str(data.get("db_only_action", "change")).upper()
    return "\n".join(
        [
            f"yaml-only (reload will CREATE): {data.get('yaml_only', [])}",
            f"db-only   (reload will {action}): {data.get('db_only', [])}",
            f"in-both   (reload will UPDATE): {data.get('both', [])}",
        ]
    )


def _domain_config_status(domain: str) -> dict[str, Any]:
    """Fetch yaml↔DB diff + latest recorded version for one config *domain*.

    *domain* is ``"sources"`` or ``"subscriptions"``. Errors are folded into the
    returned dict (never raised) so one domain failing does not hide the other.
    """
    base = f"{_base_url()}/api/v1/{domain}/config"
    diff_resp = _http(lambda: httpx.get(f"{base}/diff", headers=_get_headers()))
    versions_resp = _http(
        lambda: httpx.get(f"{base}/versions?limit=1", headers=_get_headers())
    )
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


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    api_url: str | None = typer.Option(None, "--api-url", help="API base URL"),
    api_key: str | None = typer.Option(None, "--api-key", help="API key"),
) -> None:
    """IntelliSource CLI."""
    enforce_utf8_runtime()
    load_provider_env()
    settings = get_settings()
    if api_url is not None:
        _state["api_url"] = api_url
    elif settings.api_url:
        _state["api_url"] = settings.api_url

    if api_key is not None:
        _state["api_key"] = api_key
    elif settings.api_key:
        _state["api_key"] = settings.api_key

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# Docker stack lifecycle (cross-platform — no make / POSIX shell required)
# ---------------------------------------------------------------------------

_COMPOSE_FILE_PARTS = ("docker", "docker-compose.yml")


def _compose_args(*args: str) -> list[str]:
    """Build a ``docker compose -f <root>/docker/docker-compose.yml ...`` argv.

    Uses the v2 ``docker compose`` (space) form and an absolute compose-file
    path anchored at the project root, so it behaves identically from any CWD
    on Windows PowerShell, macOS, and Linux.
    """
    compose_file = project_root().joinpath(*_COMPOSE_FILE_PARTS)
    return ["docker", "compose", "-f", str(compose_file), *args]


def _run_compose(*args: str) -> None:
    """Run a docker compose subcommand, surfacing failures as a CLI exit code.

    ``shell=False`` with an argv list keeps the space-containing compose path
    safe on Windows PowerShell (no shell quoting of ``C:\\Program Files\\...``).
    """
    argv = _compose_args(*args)
    try:
        result = subprocess.run(argv, shell=False)  # noqa: S603
    except FileNotFoundError:
        typer.echo(
            "Error: 'docker' not found on PATH. Install Docker Desktop and retry."
        )
        raise typer.Exit(code=1) from None
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


@app.command("up")
def up() -> None:
    """Start the full stack and block until services report healthy.

    ``--wait`` holds until the API healthcheck passes, so a follow-up
    ``doctor --check-api`` / ``task trigger`` does not race uvicorn's boot
    (the published port answers before the app is serving).
    """
    _run_compose("up", "-d", "--wait")


@app.command("down")
def down() -> None:
    """Stop and remove the stack containers."""
    _run_compose("down")


@app.command("migrate")
def migrate() -> None:
    """Run database migrations (alembic upgrade head) in a one-off container."""
    _run_compose("run", "--rm", "migrate")


@app.command("logs")
def logs() -> None:
    """Follow logs from all stack services (Ctrl-C to stop)."""
    _run_compose("logs", "-f")


@app.command("ps")
def ps() -> None:
    """Show status of the stack containers."""
    _run_compose("ps")


# ---------------------------------------------------------------------------
# source commands
# ---------------------------------------------------------------------------


@source_app.command("list")
def source_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all sources."""
    url = f"{_base_url()}/api/v1/sources"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    _emit(resp.json(), json_output=json_output)


@source_app.command("show")
def source_show(
    source_id: str = typer.Argument(..., help="Source ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show a single source's full config (vertical detail view)."""
    url = f"{_base_url()}/api/v1/sources/{source_id}"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(_format_detail(data))


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
    resp = _http(lambda: httpx.post(api_url, json=payload, headers=_get_headers()))
    _emit(resp.json(), json_output=json_output)


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
    url_path = f"{_base_url()}/api/v1/sources/{source_id}"
    resp = _http(lambda: httpx.patch(url_path, json=payload, headers=_get_headers()))
    if resp.status_code >= 400:
        typer.echo(f"Error ({resp.status_code}): {resp.text}")
        raise typer.Exit(code=1)
    _emit(resp.json(), json_output=json_output)


@source_app.command("delete")
def source_delete(
    source_id: str = typer.Argument(..., help="Source ID"),
) -> None:
    """Delete a source."""
    url = f"{_base_url()}/api/v1/sources/{source_id}"
    _http(lambda: httpx.delete(url, headers=_get_headers()))
    typer.echo("Deleted.")


@source_app.command("versions")
def source_versions(
    limit: int = typer.Option(20, "--limit", help="Max versions to list"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List recorded source config version snapshots (for rollback)."""
    url = f"{_base_url()}/api/v1/sources/config/versions?limit={limit}"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(_format_table({"items": data.get("versions", [])}))


@source_app.command("diff")
def source_diff(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Diff the sources yaml SSOT against current DB state (reload preview)."""
    url = f"{_base_url()}/api/v1/sources/config/diff"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    if resp.status_code >= 400:
        typer.echo(f"Error ({resp.status_code}): {resp.text}")
        raise typer.Exit(code=1)
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(_format_diff(data))


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
    resp = _http(lambda: httpx.post(url, json=payload, headers=_get_headers()))
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
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
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
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
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
    resp = _http(lambda: httpx.post(url, json=payload, headers=_get_headers()))
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

# Provider key subset of the authoritative settings.PROVIDER_ENV_KEYS list
# (excludes AZURE_API_BASE / AZURE_API_VERSION, which are endpoints not keys).
_PROVIDER_API_KEYS = tuple(k for k in PROVIDER_ENV_KEYS if k.endswith("_API_KEY"))


def _load_dotenv_file(path: str) -> dict[str, str]:
    """Parse a .env file into a dict; skip comments and blank lines."""
    result: dict[str, str] = {}
    p = pathlib.Path(path)
    if not p.exists():
        return result
    for raw in read_text(p).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _dir_check(label: str, raw_dir: str, root: pathlib.Path) -> tuple[str, bool, str]:
    """Check a config directory exists and holds at least one YAML file."""
    directory = pathlib.Path(raw_dir)
    if not directory.is_absolute():
        directory = root / raw_dir
    if not directory.is_dir():
        return (f"{label} ({raw_dir})", False, "directory missing")
    yamls = [
        f for f in directory.iterdir() if f.suffix in (".yaml", ".yml") and f.is_file()
    ]
    if yamls:
        return (f"{label} ({raw_dir})", True, f"{len(yamls)} YAML file(s)")
    return (f"{label} ({raw_dir})", False, "no YAML files found")


def _doctor_env(env: dict[str, str]) -> list[tuple[str, bool | None, str]]:
    """Return a list of (label, ok, message) checks.

    ``ok`` is True/False for required items and None for optional ones.
    Relative config paths are anchored at the project root so the report is
    correct regardless of the current working directory.
    """
    items: list[tuple[str, bool | None, str]] = []
    root = project_root()

    api_key = env.get("IS_API_KEY", "")
    if api_key == _API_KEY_PLACEHOLDER:
        items.append(("IS_API_KEY", False, "default placeholder — change before use"))
    elif not api_key:
        items.append(("IS_API_KEY", False, "not set"))
    else:
        items.append(("IS_API_KEY", True, "set"))

    db_url = env.get("IS_DATABASE_URL", "")
    if not db_url:
        items.append(("IS_DATABASE_URL", False, "not set"))
    elif "asyncpg" not in db_url:
        items.append(
            (
                "IS_DATABASE_URL",
                False,
                "should use the asyncpg driver (postgresql+asyncpg://...)",
            )
        )
    else:
        items.append(("IS_DATABASE_URL", True, "set"))

    for var in ["IS_REDIS_URL", "IS_CELERY_BROKER_URL"]:
        val = env.get(var, "")
        items.append((var, bool(val), "set" if val else "not set"))

    llm_key = next((k for k in _PROVIDER_API_KEYS if env.get(k)), None)
    if llm_key:
        items.append(("LLM key", True, f"{llm_key} set"))
    else:
        items.append(("LLM key", False, f"none of {', '.join(_PROVIDER_API_KEYS)} set"))

    llm_cfg = env.get("IS_LLM_CONFIG_PATH", "config/llm_models.yaml")
    llm_cfg_path = pathlib.Path(llm_cfg)
    if not llm_cfg_path.is_absolute():
        llm_cfg_path = root / llm_cfg
    items.append(
        (
            f"llm config ({llm_cfg})",
            llm_cfg_path.is_file(),
            "found" if llm_cfg_path.is_file() else "file missing",
        )
    )

    items.append(
        _dir_check(
            "sources dir", env.get("IS_SOURCE_CONFIG_DIR", "config/sources"), root
        )
    )
    items.append(
        _dir_check(
            "subscriptions dir",
            env.get("IS_SUBSCRIPTION_CONFIG_DIR", "config/subscriptions"),
            root,
        )
    )

    for channel, vars_ in _REQUIRED_CHANNEL_VARS:
        missing = [v for v in vars_ if not env.get(v)]
        if missing:
            items.append(
                (f"channel {channel}", None, f"optional — {', '.join(missing)} not set")
            )
        else:
            items.append((f"channel {channel}", True, "configured"))

    return items


_HEALTH_PROBE_ATTEMPTS = 5
_HEALTH_PROBE_BACKOFF_SECONDS = 1.0


def _probe_api_health(
    *,
    attempts: int = _HEALTH_PROBE_ATTEMPTS,
    backoff: float = _HEALTH_PROBE_BACKOFF_SECONDS,
    notify: Callable[[str], None] | None = None,
) -> tuple[str, dict[str, Any] | str]:
    """Probe ``GET /health`` with retries, classifying the outcome.

    Returns ``(outcome, payload)`` where outcome is one of:

    - ``"ok"``       — a parseable JSON body (payload = the decoded body)
    - ``"starting"`` — reachable but not serving a complete response yet:
      empty / invalid body, read timeout, mid-response disconnect, or 5xx
      (payload = a short detail string)
    - ``"down"``     — connection refused / DNS failure / connect timeout
      (payload = a short detail string)

    A freshly-started stack accepts the published port (docker-proxy) before
    uvicorn finishes lifespan startup; the body is empty there and
    ``resp.json()`` raises ``Expecting value: line 1 column 1 (char 0)``.
    Retrying lets that transient window self-heal instead of being reported
    as a hard failure. ``notify`` (if given) is called once per pending retry
    so a caller can surface progress rather than blocking silently.
    """
    url = f"{_base_url()}/health"
    outcome, payload = "down", "no response"
    for attempt in range(attempts):
        try:
            resp = httpx.get(url, timeout=3)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            outcome, payload = "down", str(exc) or type(exc).__name__
        except httpx.HTTPError as exc:
            outcome, payload = "starting", str(exc) or type(exc).__name__
        except Exception as exc:  # noqa: BLE001 — doctor must never traceback
            outcome, payload = "down", str(exc) or type(exc).__name__
        else:
            if resp.status_code >= 500:
                outcome, payload = "starting", f"HTTP {resp.status_code}"
            else:
                try:
                    return "ok", resp.json()
                except (json.JSONDecodeError, ValueError):
                    outcome, payload = "starting", "empty or invalid JSON body"
        if attempt < attempts - 1:
            if notify is not None:
                notify(f"waiting for API (attempt {attempt + 2}/{attempts})")
            time.sleep(backoff)
    return outcome, payload


@app.command("doctor")
def doctor(
    env_file: str | None = typer.Option(
        None,
        "--env-file",
        help=".env file to inspect (default: <root>/docker/.env;"
        " override with IS_ENV_FILE)",
    ),
    check_api: bool = typer.Option(
        False, "--check-api", help="Try to reach the running API"
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Exit 1 if any required item missing"
    ),
) -> None:
    """Check configuration and report missing or misconfigured items."""
    if env_file is None:
        env_file = os.environ.get("IS_ENV_FILE") or str(
            project_root() / "docker" / ".env"
        )
    env = {**_load_dotenv_file(env_file), **os.environ}
    typer.echo(f"Inspecting {env_file}\n")

    items = _doctor_env(env)
    errors = 0
    for label, ok, msg in items:
        if ok is True:
            typer.echo(f"  [OK]  {label:<35} {msg}")
        elif ok is False:
            typer.echo(f"  [FAIL]  {label:<35} {msg}", err=False)
            errors += 1
        else:
            typer.echo(f"  [--]  {label:<35} {msg}")

    if check_api:
        outcome, payload = _probe_api_health(
            notify=lambda msg: typer.echo(f"  [..]  {'API /health':<35} {msg}")
        )
        if outcome == "ok" and isinstance(payload, dict):
            status = payload.get("status", "unknown")
            typer.echo(f"  [OK]  {'API /health':<35} {status}")
            for w in payload.get("missing_config", []) or []:
                typer.echo(f"  [--]  {'API warning':<35} {w}")
        elif outcome == "starting":
            typer.echo(
                f"  [--]  {'API /health':<35} "
                "starting up — not serving yet; re-run shortly"
            )
            # In strict mode a not-ready API is a gate failure; interactively
            # it is just a soft note (it self-heals once boot completes).
            if strict:
                errors += 1
        else:
            typer.echo(
                f"  [FAIL]  {'API /health':<35} "
                f"unreachable ({payload}) — start it with `intellisource up`"
            )
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


def _topic_source_entry(src: Any) -> dict[str, Any]:
    """Serialize a TopicSource into a SourceConfig-shaped YAML entry."""
    entry: dict[str, Any] = {"name": src.name, "type": src.type, "url": src.url}
    if src.tags:
        entry["tags"] = list(src.tags)
    if src.discipline_tags:
        entry["discipline_tags"] = list(src.discipline_tags)
    entry["schedule_interval"] = src.schedule_interval
    if not src.schedule_adaptive:
        entry["schedule_adaptive"] = src.schedule_adaptive
    if src.metadata:
        entry["metadata"] = dict(src.metadata)
    return entry


def _materialize_topic_sources(topic: Any, sources_dir: pathlib.Path) -> pathlib.Path:
    """Write a topic's sources to ``<sources_dir>/topic-<id>.yaml`` and return path."""
    import yaml

    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / f"topic-{topic.id}.yaml"
    payload = {"sources": [_topic_source_entry(s) for s in topic.sources]}
    header = f"# IntelliSource 内置主题信源: {topic.name} ({topic.id})\n"
    body = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    path.write_text(header + body, encoding="utf-8")
    return path


def _select_topics(topics_arg: str | None, non_interactive: bool) -> list[Any]:
    """Resolve which built-in topics to materialize during ``init``.

    ``topics_arg`` is a comma-separated list of ids (used in non-interactive /
    scripted runs); when absent and interactive, the user picks from a menu.
    """
    from intellisource.topic.loader import TopicLoader

    all_topics = TopicLoader().load_all()
    by_id = {t.id: t for t in all_topics}

    def _resolve_token(tok: str) -> Any | None:
        tok = tok.strip()
        if not tok:
            return None
        if tok.isdigit():
            idx = int(tok) - 1
            return all_topics[idx] if 0 <= idx < len(all_topics) else None
        if tok in by_id:
            return by_id[tok]
        typer.echo(f"  Warning: unknown topic {tok!r} — skipped")
        return None

    if topics_arg is not None:
        raw = topics_arg
    elif non_interactive:
        return []
    else:
        typer.echo("\nBuilt-in topics (学科 discipline / 行业 industry):")
        for i, t in enumerate(all_topics, 1):
            typer.echo(
                f"  {i}. {t.id}  —  {t.name} [{t.dimension}] ({len(t.sources)} sources)"
            )
        raw = typer.prompt(
            "Select topics to add sources for "
            "(comma-separated numbers or ids, blank to skip)",
            default="",
        )

    chosen: list[Any] = []
    seen: set[str] = set()
    for tok in raw.split(","):
        topic = _resolve_token(tok)
        if topic is not None and topic.id not in seen:
            seen.add(topic.id)
            chosen.append(topic)
    return chosen


def _write_env_file(path: pathlib.Path, updates: dict[str, str]) -> None:
    """Merge ``updates`` into an existing .env file (or create from .env.example)."""
    example = project_root() / "docker" / ".env.example"
    if path.exists():
        lines = read_text(path).splitlines()
    elif example.exists():
        lines = read_text(example).splitlines()
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

    write_text(path, "\n".join(out) + "\n")


_PROVIDER_BY_CHOICE = {"1": "deepseek", "2": "openai", "3": "anthropic"}


def _seed_from_example(example: pathlib.Path, target: pathlib.Path) -> bool:
    """Copy *example* to *target* when *target* is absent. Returns True if written.

    Idempotent: an existing target is left untouched, so re-running init is safe.
    """
    if target.exists() or not example.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text(target, read_text(example))
    return True


def _resolve_provider(provider: str | None, non_interactive: bool) -> str:
    """Resolve the LLM provider, validating explicit input and re-prompting.

    An out-of-range interactive choice re-prompts rather than silently falling
    back, so the user never ends up on a provider they did not pick.
    """
    if provider is not None:
        chosen = provider.lower()
        if chosen not in _PROVIDER_ENV:
            raise typer.BadParameter(
                f"--provider must be one of {', '.join(_PROVIDER_ENV)}"
            )
        return chosen
    if non_interactive:
        return "deepseek"
    typer.echo("\nLLM provider:")
    typer.echo("  1. DeepSeek  (recommended — low cost)")
    typer.echo("  2. OpenAI")
    typer.echo("  3. Anthropic")
    while True:
        choice = typer.prompt("Choose (1/2/3)", default="1")
        chosen = _PROVIDER_BY_CHOICE.get(choice, "")
        if chosen in _PROVIDER_ENV:
            return chosen
        typer.echo(f"  Invalid choice {choice!r} — enter 1, 2, or 3.")


def _prompt_smtp_port() -> str:
    """Prompt for an SMTP port, re-prompting until it is a valid 1-65535 int."""
    while True:
        port: str = typer.prompt("IS_SMTP_PORT", default="587")
        if port.isdigit() and 1 <= int(port) <= 65535:
            return port
        typer.echo(f"  Invalid port {port!r} — enter an integer 1-65535.")


def _prompt_channel() -> dict[str, str]:
    """Interactive distribution-channel prompts; returns the .env updates."""
    typer.echo("\nDistribution channel (optional — can add later):")
    typer.echo("  1. WeWork / 企业微信  (recommended)")
    typer.echo("  2. WeChat Official Account")
    typer.echo("  3. Email SMTP")
    typer.echo("  4. Skip for now")
    ch_choice = typer.prompt("Choose (1/2/3/4)", default="4")
    updates: dict[str, str] = {}
    if ch_choice == "1":
        updates["IS_WEWORK_CORP_ID"] = typer.prompt("IS_WEWORK_CORP_ID")
        updates["IS_WEWORK_CORP_SECRET"] = typer.prompt("IS_WEWORK_CORP_SECRET")
        updates["IS_WEWORK_AGENT_ID"] = typer.prompt("IS_WEWORK_AGENT_ID")
    elif ch_choice == "2":
        updates["IS_WECHAT_APP_ID"] = typer.prompt("IS_WECHAT_APP_ID")
        updates["IS_WECHAT_APP_SECRET"] = typer.prompt("IS_WECHAT_APP_SECRET")
        updates["IS_WECHAT_WEBHOOK_TOKEN"] = typer.prompt(
            "IS_WECHAT_WEBHOOK_TOKEN", default=""
        )
    elif ch_choice == "3":
        updates["IS_SMTP_HOST"] = typer.prompt("IS_SMTP_HOST")
        updates["IS_SMTP_USER"] = typer.prompt("IS_SMTP_USER")
        updates["IS_SMTP_PASSWORD"] = typer.prompt("IS_SMTP_PASSWORD", hide_input=True)
        updates["IS_SMTP_PORT"] = _prompt_smtp_port()
        updates["IS_SMTP_USE_TLS"] = typer.prompt(
            "IS_SMTP_USE_TLS (true/false)", default="true"
        )
    return updates


@app.command("init")
def init(
    env_file: str | None = typer.Option(
        None, "--env-file", help="Path to write .env (default: <root>/docker/.env)"
    ),
    sources_file: str | None = typer.Option(
        None,
        "--sources-file",
        help="Path to write sources YAML (default: <root>/config/sources/sources.yaml)",
    ),
    provider: str | None = typer.Option(
        None, "--provider", help="LLM provider: deepseek / openai / anthropic"
    ),
    topics: str | None = typer.Option(
        None,
        "--topics",
        help="Comma-separated built-in topic ids to materialize as source files"
        " (e.g. 'artificial-intelligence,electrical-engineering').",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        "--yes",
        "-y",
        help="Run without prompts (CI / scripted): auto-generate the API key,"
        " take the provider from --provider or env, skip channel setup.",
    ),
) -> None:
    """First-time setup — run on the HOST, before ``intellisource up``.

    Writes docker/.env, seeds the llm_models / subscriptions config templates,
    and writes a starter sources file. The stack mounts ``config`` read-only,
    so this must run on the host machine, never inside a container.
    """
    root = project_root()
    env_path = pathlib.Path(env_file) if env_file else root / "docker" / ".env"
    sources_path = (
        pathlib.Path(sources_file)
        if sources_file
        else root / "config" / "sources" / "sources.yaml"
    )

    typer.echo("Welcome to IntelliSource setup.\n")

    # --- API key ---
    if non_interactive:
        api_key = os.environ.get("IS_API_KEY") or secrets.token_hex(32)
    else:
        api_key = typer.prompt(
            "API key for IntelliSource (leave blank to auto-generate)", default=""
        )
        if not api_key:
            api_key = secrets.token_hex(32)
            typer.echo(f"Generated: {api_key}")

    # --- LLM provider ---
    chosen_provider = _resolve_provider(provider, non_interactive)
    llm_key_var = _PROVIDER_ENV[chosen_provider]
    if non_interactive:
        llm_key_val = os.environ.get(llm_key_var, "")
        if not llm_key_val:
            typer.echo(f"  Warning: {llm_key_var} not set — set it before first use.")
    else:
        llm_key_val = typer.prompt(llm_key_var)

    # --- Distribution channel (interactive only) ---
    channel_updates = {} if non_interactive else _prompt_channel()

    # --- Write .env ---
    env_path.parent.mkdir(parents=True, exist_ok=True)
    updates: dict[str, str] = {"IS_API_KEY": api_key, llm_key_var: llm_key_val}
    updates.update(channel_updates)
    _write_env_file(env_path, updates)
    typer.echo(f"\n[OK] Written {env_path}")

    # --- Seed config templates (fixes provider mismatch via llm_models.yaml) ---
    if _seed_from_example(
        root / "config" / "llm_models.example.yaml",
        root / "config" / "llm_models.yaml",
    ):
        typer.echo("[OK] Created config/llm_models.yaml")
    if _seed_from_example(
        root / "config" / "subscriptions.example.yaml",
        root / "config" / "subscriptions" / "subscriptions.yaml",
    ):
        typer.echo("[OK] Created config/subscriptions/subscriptions.yaml")

    # --- Starter source ---
    add_starter = non_interactive or typer.confirm(
        "\nAdd Hacker News RSS as a starter source?", default=True
    )
    if add_starter:
        sources_path.parent.mkdir(parents=True, exist_ok=True)
        if not sources_path.exists():
            write_text(sources_path, _DEFAULT_HN_SOURCE)
            typer.echo(f"[OK] Written {sources_path}")
        else:
            typer.echo(f"  {sources_path} already exists — skipped")

    # --- Built-in topics → materialize their sources as files (host-side) ---
    selected_topics = _select_topics(topics, non_interactive)
    for topic in selected_topics:
        written = _materialize_topic_sources(topic, sources_path.parent)
        typer.echo(
            f"[OK] Wrote {len(topic.sources)} sources for topic {topic.id} → {written}"
        )
    if selected_topics:
        typer.echo(
            "  After `up`, run `intellisource topic enable <id> --channel ...`"
            " to create the matching subscription."
        )

    # --- Next steps ---
    typer.echo("\nNext steps:")
    typer.echo("  uv run intellisource up                        # start the stack")
    typer.echo("  uv run intellisource doctor --check-api        # verify config")
    typer.echo("  uv run intellisource topic list                # built-in topics")
    typer.echo("  uv run intellisource topic enable <id> --channel wework")
    typer.echo("  uv run intellisource subscriptions reload      # load subscriptions")
    typer.echo("  uv run intellisource task trigger <source-id>  # first collection")
    typer.echo(
        "\nTip: daily/weekly subscriptions support a digest `template` +"
        " `render_mode` (code | llm-assisted | llm-freeform)."
    )
    typer.echo(
        "     See config/subscriptions/subscriptions.yaml comments or"
        " `subscriptions add --help`."
    )


# ---------------------------------------------------------------------------
# subscriptions sub-app (B-055 — HTTP shell over /api/v1/subscriptions/*)
# ---------------------------------------------------------------------------


def _post_json(path: str, payload: dict[str, Any]) -> httpx.Response:
    return _http(
        lambda: httpx.post(f"{_base_url()}{path}", json=payload, headers=_get_headers())
    )


# ---------------------------------------------------------------------------
# template command group (custom digest templates)
# ---------------------------------------------------------------------------


@template_app.command("list")
def template_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List digest templates (built-in + custom)."""
    url = f"{_base_url()}/api/v1/templates"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    _emit(resp.json(), json_output=json_output)


@template_app.command("show")
def template_show(
    name: str = typer.Argument(..., help="Template name"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show a template's detail by name (built-in or custom)."""
    url = f"{_base_url()}/api/v1/templates/{name}"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    _emit(resp.json(), json_output=json_output)


@template_app.command("add")
def template_add(
    name: str = typer.Option(..., "--name", help="Template name"),
    base_template: str = typer.Option(
        ..., "--base", help="Built-in base template (e.g. daily-brief, push-card)"
    ),
    formats: str = typer.Option(
        ..., "--formats", help="Comma-separated formats (e.g. markdown,text)"
    ),
    default_format: str = typer.Option(..., "--default-format", help="Default format"),
    source: str | None = typer.Option(
        None, "--source", help="Jinja source applied to the default format"
    ),
    title: str | None = typer.Option(
        None, "--title", help="aggregate_config.title override"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Create or replace a custom digest template."""
    fmt_list = [f.strip() for f in formats.split(",") if f.strip()]
    jinja_source: dict[str, str] = {}
    if source is not None:
        jinja_source[default_format] = source
    aggregate_config: dict[str, Any] = {}
    if title is not None:
        aggregate_config["title"] = title
    payload: dict[str, Any] = {
        "name": name,
        "base_template": base_template,
        "formats": fmt_list,
        "default_format": default_format,
        "jinja_source": jinja_source,
        "aggregate_config": aggregate_config,
    }
    resp = _post_json("/api/v1/templates", payload)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text
        typer.echo(f"Error ({resp.status_code}): {detail}")
        raise typer.Exit(code=1)
    _emit(resp.json(), json_output=json_output)


@template_app.command("rm")
def template_rm(
    name: str = typer.Argument(..., help="Template name"),
) -> None:
    """Delete a custom template by name."""
    url = f"{_base_url()}/api/v1/templates/{name}"
    resp = _http(lambda: httpx.delete(url, headers=_get_headers()))
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    typer.echo("Deleted.")


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
    url = f"{_base_url()}/api/v1/subscriptions"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    _emit(resp.json(), json_output=json_output)


@subscriptions_app.command("show")
def subscriptions_show(
    sub_id: str = typer.Argument(..., help="Subscription id (uuid)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show one subscription's full config + the effective digest render mode."""
    url = f"{_base_url()}/api/v1/subscriptions/{sub_id}"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(_format_detail(data))
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
    resp = _post_json("/api/v1/subscriptions", payload)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text
        typer.echo(f"Error ({resp.status_code}): {detail}")
        raise typer.Exit(code=1)
    _emit(resp.json(), json_output=json_output)


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
    base = f"{_base_url()}/api/v1/subscriptions/{sub_id}"
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
        current = _http(lambda: httpx.get(base, headers=_get_headers()))
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
    resp = _http(lambda: httpx.patch(base, json=body, headers=_get_headers()))
    if resp.status_code >= 400:
        typer.echo(f"Error ({resp.status_code}): {resp.text}")
        raise typer.Exit(code=1)
    _emit(resp.json(), json_output=json_output)


@subscriptions_app.command("rm")
def subscriptions_rm(
    sub_id: str = typer.Argument(..., help="Subscription id (uuid)"),
) -> None:
    """Soft-delete (paused) a subscription by id."""
    url = f"{_base_url()}/api/v1/subscriptions/{sub_id}"
    resp = _http(lambda: httpx.delete(url, headers=_get_headers()))
    if resp.status_code == 404:
        typer.echo("Not found")
        raise typer.Exit(code=1)
    typer.echo("Paused.")


@subscriptions_app.command("reload")
def subscriptions_reload(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Reload all subscriptions from yaml (records a new version snapshot)."""
    resp = _post_json("/api/v1/subscriptions/reload", {})
    _emit(resp.json(), json_output=json_output)


@subscriptions_app.command("rollback")
def subscriptions_rollback(
    version: str = typer.Argument(..., help="Version label to rollback to (e.g. '1')"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Rollback subscriptions to a previously recorded version snapshot."""
    resp = _post_json(f"/api/v1/subscriptions/config/rollback/{version}", {})
    if resp.status_code == 404:
        typer.echo(f"Version {version!r} not found")
        raise typer.Exit(code=1)
    _emit(resp.json(), json_output=json_output)


@subscriptions_app.command("versions")
def subscriptions_versions(
    limit: int = typer.Option(20, "--limit", help="Max versions to list"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List recorded subscription config version snapshots (for rollback)."""
    url = f"{_base_url()}/api/v1/subscriptions/config/versions?limit={limit}"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(_format_table({"items": data.get("versions", [])}))


@subscriptions_app.command("diff")
def subscriptions_diff(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Diff the subscriptions yaml SSOT against DB state (reload preview)."""
    url = f"{_base_url()}/api/v1/subscriptions/config/diff"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    if resp.status_code >= 400:
        typer.echo(f"Error ({resp.status_code}): {resp.text}")
        raise typer.Exit(code=1)
    data = resp.json()
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(_format_diff(data))


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
            typer.echo(_format_diff(diff))
        typer.echo("")


@topic_app.command("list")
def topic_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List the built-in collection topics (discipline / industry packs)."""
    url = f"{_base_url()}/api/v1/topics"
    resp = _http(lambda: httpx.get(url, headers=_get_headers()))
    _emit(resp.json(), json_output=json_output)


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
    resp = _post_json(f"/api/v1/topics/{topic_id}/enable", payload)
    if resp.status_code == 404:
        typer.echo(f"Topic {topic_id!r} not found")
        raise typer.Exit(code=1)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text
        typer.echo(f"Error ({resp.status_code}): {detail}")
        raise typer.Exit(code=1)
    _emit(resp.json(), json_output=json_output)
