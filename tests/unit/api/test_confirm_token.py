"""confirm_token: signed HITL approval round-trip for confirm-gated tools.

The token lets the conversational agent defer a confirm-gated call (e.g.
distribute) to the user: the endpoint mints it from the pending {tool, args},
the client replays it on approval, and the runner recovers the exact calls.
Tampering must invalidate the token so an unapproved action never runs.
"""

from __future__ import annotations

from intellisource.api.confirm_token import mint_confirm_token, parse_confirm_token


def test_roundtrip_preserves_tool_and_args() -> None:
    calls = [
        {"tool": "distribute", "args": {"content_id": "c1", "subscription_id": "s1"}}
    ]
    token = mint_confirm_token(calls)

    parsed = parse_confirm_token(token)

    assert parsed == [
        {"tool": "distribute", "args": {"content_id": "c1", "subscription_id": "s1"}}
    ]


def test_roundtrip_multiple_calls() -> None:
    calls = [
        {"tool": "distribute", "args": {"content_id": "c1"}},
        {"tool": "distribute", "args": {"content_id": "c2"}},
    ]
    parsed = parse_confirm_token(mint_confirm_token(calls))
    assert parsed is not None
    assert [c["args"]["content_id"] for c in parsed] == ["c1", "c2"]


def test_tampered_payload_is_rejected() -> None:
    token = mint_confirm_token([{"tool": "distribute", "args": {"content_id": "c1"}}])
    payload_b64, sig_b64 = token.split(".", 1)
    # forge a different payload while keeping the original signature
    forged = mint_confirm_token([{"tool": "delete_source", "args": {"source_id": "x"}}])
    forged_payload = forged.split(".", 1)[0]

    assert parse_confirm_token(f"{forged_payload}.{sig_b64}") is None


def test_garbage_and_empty_tokens_return_none() -> None:
    assert parse_confirm_token(None) is None
    assert parse_confirm_token("") is None
    assert parse_confirm_token("not-a-token") is None
    assert parse_confirm_token("a.b.c") is None


def test_empty_calls_token_parses_to_none() -> None:
    # a token carrying no usable calls is treated as "nothing approved"
    assert parse_confirm_token(mint_confirm_token([])) is None
