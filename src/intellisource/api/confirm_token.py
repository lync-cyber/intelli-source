"""Integrity-protected confirm token for human-in-the-loop tool approval.

When the conversational agent proposes a confirm-gated tool (e.g. ``distribute``)
the ``/agent/chat`` endpoint mints a token capturing the exact pending calls
(tool + args). The client shows them to the user; on approval it returns the
token on the next turn and the runner executes exactly those approved calls.

The token is signed with the configured API key (the same secret already gating
the endpoint), so it cannot be tampered with. When no key is set (dev) a fixed
fallback secret keeps the round-trip working.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from typing import Any

from intellisource.core.settings import get_settings

_DEV_FALLBACK_SECRET = "intellisource-dev-confirm-secret"


def _secret() -> bytes:
    return (get_settings().api_key or _DEV_FALLBACK_SECRET).encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _normalise(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project calls to the minimal {tool, args} shape the token carries."""
    out: list[dict[str, Any]] = []
    for call in calls:
        tool = call.get("tool")
        if not tool:
            continue
        out.append({"tool": str(tool), "args": call.get("args") or {}})
    return out


def mint_confirm_token(calls: list[dict[str, Any]]) -> str:
    """Return a signed token encoding the pending calls (tool + args)."""
    payload = json.dumps(
        _normalise(calls), sort_keys=True, default=str, separators=(",", ":")
    ).encode("utf-8")
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return f"{_b64e(payload)}.{_b64e(sig)}"


def parse_confirm_token(token: str | None) -> list[dict[str, Any]] | None:
    """Return the approved calls from a valid token, or None when absent/invalid.

    Rejects a missing, malformed, or tamper-signed token by returning None so
    the caller treats the turn as unapproved (the action stays pending).
    """
    if not token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _b64d(payload_b64)
        sig = _b64d(sig_b64)
    except (ValueError, binascii.Error):
        return None
    expected = hmac.new(_secret(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    calls = _normalise([c for c in data if isinstance(c, dict)])
    return calls or None
