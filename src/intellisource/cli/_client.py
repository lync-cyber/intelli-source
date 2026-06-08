"""HTTP transport + shared client state for the CLI commands.

All command modules route their requests through the verb helpers here so the
``httpx`` reference lives in exactly one place (a single point to configure
headers / timeouts, and a single patch target in tests).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import typer

DEFAULT_API_URL = "http://localhost:8000"

# POST timeout. httpx defaults to 5s, but /search/chat blocks for a whole
# multi-step LLM agent loop, so a generous read timeout keeps the client from
# raising ReadTimeout while the server is still synthesising the answer.
_POST_TIMEOUT = httpx.Timeout(180.0, connect=10.0)

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


def base_url() -> str:
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


def error_message(resp: httpx.Response) -> str:
    """Extract the human message from the ``{"error": {...}}`` envelope.

    Falls back to a top-level ``detail`` field when the envelope is absent.
    """
    try:
        body = resp.json()
    except Exception:
        return ""
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("message", "") or "")
    return str(body.get("detail", "") or "")


def get(path: str) -> httpx.Response:
    return _http(lambda: httpx.get(f"{base_url()}{path}", headers=_get_headers()))


def delete(path: str) -> httpx.Response:
    return _http(lambda: httpx.delete(f"{base_url()}{path}", headers=_get_headers()))


def patch(path: str, payload: dict[str, Any]) -> httpx.Response:
    return _http(
        lambda: httpx.patch(f"{base_url()}{path}", json=payload, headers=_get_headers())
    )


def post(path: str, payload: dict[str, Any]) -> httpx.Response:
    return _http(
        lambda: httpx.post(f"{base_url()}{path}", json=payload, headers=_get_headers())
    )


def post_json(path: str, payload: dict[str, Any]) -> httpx.Response:
    """POST with the generous read timeout used for LLM-backed endpoints."""
    return _http(
        lambda: httpx.post(
            f"{base_url()}{path}",
            json=payload,
            headers=_get_headers(),
            timeout=_POST_TIMEOUT,
        )
    )
