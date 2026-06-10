"""CLI tool for IntelliSource API interaction.

Assembles the Typer app from the per-domain command modules in
``intellisource.cli.commands``. Transport lives in ``cli._client`` and output
formatting in ``cli._format``.
"""

from __future__ import annotations

import typer

from intellisource.cli import _client
from intellisource.cli.commands import (
    chat,
    config,
    content,
    doctor,
    init,
    pipeline,
    search,
    source,
    stack,
    subscription,
    task,
    template,
    topic,
)

# Re-exported so callers / tests can keep importing them from cli.main.
from intellisource.cli.commands.doctor import (  # noqa: F401
    _doctor_env,
    _load_dotenv_file,
    _probe_api_health,
)
from intellisource.core.encoding import (
    enforce_utf8_runtime,
    reexec_in_utf8_mode_if_needed,
)
from intellisource.core.settings import get_settings, load_provider_env

app = typer.Typer()

app.add_typer(content.content_app, name="content")
app.add_typer(source.source_app, name="source")
app.add_typer(task.task_app, name="task")
app.add_typer(pipeline.pipeline_app, name="pipeline")
app.add_typer(subscription.subscriptions_app, name="subscriptions")
app.add_typer(topic.topic_app, name="topic")
app.add_typer(config.config_app, name="config")
app.add_typer(template.template_app, name="template")

stack.register(app)
search.register(app)
chat.register(app)
doctor.register(app)
init.register(app)


def run() -> None:
    """Console-script entrypoint: enter UTF-8 mode (re-exec if needed) then dispatch.

    Runs before typer parses argv so help text and parse errors are emitted in
    UTF-8 too. Tests drive ``app`` directly via ``CliRunner`` and never hit this,
    so the re-exec can only fire on a genuine standalone launch.
    """
    reexec_in_utf8_mode_if_needed()
    app()


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
        _client._state["api_url"] = api_url
    elif settings.api_url:
        _client._state["api_url"] = settings.api_url

    if api_key is not None:
        _client._state["api_key"] = api_key
    elif settings.api_key:
        _client._state["api_key"] = settings.api_key

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
