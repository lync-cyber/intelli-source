"""Top-level ``doctor`` command — config self-check + optional API probe."""

from __future__ import annotations

import json
import os
import pathlib
import time
from collections.abc import Callable
from typing import Any

import httpx
import typer

from intellisource.cli._client import base_url
from intellisource.core.encoding import read_text
from intellisource.core.paths import project_root
from intellisource.core.settings import PROVIDER_ENV_KEYS

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
        items.append(
            ("IS_DATABASE_URL", False, "not set — set IS_DATABASE_URL in .env")
        )
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
        if val:
            items.append((var, True, "set"))
        else:
            items.append((var, False, f"not set — set {var} in .env"))

    llm_key = next((k for k in _PROVIDER_API_KEYS if env.get(k)), None)
    if llm_key:
        val = env[llm_key]
        if val.endswith("..."):
            items.append(
                (
                    "LLM key",
                    False,
                    f"{llm_key} placeholder — replace with a real key in .env",
                )
            )
        else:
            items.append(("LLM key", True, f"{llm_key} set"))
    else:
        items.append(
            (
                "LLM key",
                False,
                f"none of {', '.join(_PROVIDER_API_KEYS)} set — set one in .env",
            )
        )

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
    url = f"{base_url()}/health"
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


def register(app: typer.Typer) -> None:
    """Attach the ``doctor`` command to the root *app*."""
    app.command("doctor")(doctor)
