"""Top-level ``chat`` command — RAG conversation over /agent/chat."""

from __future__ import annotations

import json
from typing import Any

import typer

from intellisource.cli import _client


def _print_chat_answer(data: dict[str, Any]) -> None:
    """Print the assistant answer followed by its cited sources, if any."""
    typer.echo(str(data.get("answer", "")))
    sources = data.get("sources") or []
    if sources:
        typer.echo("\nSources:")
        for i, src in enumerate(sources, 1):
            title = src.get("title") or "(untitled)"
            url = src.get("url")
            typer.echo(f"  [{i}] {title}" + (f"  {url}" if url else ""))


def _print_pending_confirmations(pending: list[dict[str, Any]]) -> None:
    """List the write actions the agent is holding for the user's approval."""
    typer.echo("\n需要确认的写操作:")
    for i, call in enumerate(pending, 1):
        args = json.dumps(call.get("args") or {}, ensure_ascii=False, sort_keys=True)
        typer.echo(f"  [{i}] {call.get('tool')}  {args}")


def _chat_once(
    message: str, session_id: str | None, *, confirm_token: str | None = None
) -> dict[str, Any]:
    """Send one message to /agent/chat; exit non-zero on an error response.

    The conversational agent exposes the full management toolset (search +
    source/subscription/template/pipeline CRUD + collect/process/distribute);
    write actions gated at ``confirm`` come back as ``pending_confirmations``
    with a ``confirm_token`` to replay on approval.
    """
    payload: dict[str, Any] = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    if confirm_token:
        payload["confirm_token"] = confirm_token
    resp = _client.post_json("/api/v1/agent/chat", payload)
    if resp.status_code >= 400:
        try:
            detail = _client.error_message(resp)
        except Exception:
            detail = resp.text
        typer.echo(f"Error ({resp.status_code}): {detail}")
        raise typer.Exit(code=1)
    result: dict[str, Any] = resp.json()
    return result


def _run_chat_turn(message: str, session_id: str | None) -> str | None:
    """Run one interactive turn, looping through human-in-the-loop confirmations.

    Returns the session id to carry into the next turn. When the agent proposes
    confirm-gated writes it prints them and asks for approval; on yes it replays
    the signed ``confirm_token`` so the runner executes exactly those calls.
    """
    data = _chat_once(message, session_id)
    session_id = data.get("session_id") or session_id
    _print_chat_answer(data)
    while data.get("pending_confirmations") and data.get("confirm_token"):
        _print_pending_confirmations(data["pending_confirmations"])
        if not typer.confirm("确认执行以上写操作?", default=False):
            typer.echo("已取消。")
            break
        data = _chat_once("确认执行", session_id, confirm_token=data["confirm_token"])
        session_id = data.get("session_id") or session_id
        _print_chat_answer(data)
    return session_id


def chat(
    message: str | None = typer.Argument(
        None, help="Question to ask; omit to start an interactive session"
    ),
    session_id: str | None = typer.Option(
        None, "--session-id", help="Continue an existing chat session"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output raw JSON (single-shot only)"
    ),
) -> None:
    """Chat with the IntelliSource agent via POST /agent/chat.

    The agent can search your collected sources (RAG) and manage sources /
    subscriptions / templates / pipelines and trigger runs through natural
    language; write actions require confirmation.

    With a MESSAGE it answers once and exits; without one it opens an
    interactive REPL that keeps the conversation's session across turns and
    prompts for confirmation of any write action (blank line, 'exit'/'quit',
    or Ctrl-D to leave).
    """
    if message is not None:
        data = _chat_once(message, session_id)
        if json_output:
            typer.echo(json.dumps(data))
        else:
            _print_chat_answer(data)
            if data.get("pending_confirmations"):
                _print_pending_confirmations(data["pending_confirmations"])
                typer.echo(
                    "\n提示：写操作需确认，请在交互模式 (intellisource chat) 下执行。"
                )
        return

    typer.echo("IntelliSource chat — blank line, 'exit', or Ctrl-D to quit.\n")
    current_session = session_id
    while True:
        try:
            line = typer.prompt(
                "you", prompt_suffix="> ", default="", show_default=False
            )
        except (typer.Abort, EOFError):
            typer.echo("")
            break
        msg = line.strip()
        if not msg or msg.lower() in {"exit", "quit"}:
            break
        current_session = _run_chat_turn(msg, current_session)
        typer.echo("")


def register(app: typer.Typer) -> None:
    """Attach the ``chat`` command to the root *app*."""
    app.command("chat")(chat)
