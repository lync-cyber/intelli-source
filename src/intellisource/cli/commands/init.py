"""Top-level ``init`` command — interactive first-time setup (host-side)."""

from __future__ import annotations

import os
import pathlib
import secrets
from typing import Any

import typer

from intellisource.core.encoding import read_text, write_text
from intellisource.core.paths import project_root

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

_PROVIDER_BY_CHOICE = {"1": "deepseek", "2": "openai", "3": "anthropic"}


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
        root / "config" / "examples" / "llm_models.example.yaml",
        root / "config" / "llm_models.yaml",
    ):
        typer.echo("[OK] Created config/llm_models.yaml")
    if _seed_from_example(
        root / "config" / "examples" / "subscriptions.example.yaml",
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


def register(app: typer.Typer) -> None:
    """Attach the ``init`` command to the root *app*."""
    app.command("init")(init)
