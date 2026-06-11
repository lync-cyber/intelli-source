"""Docker stack lifecycle commands (cross-platform — no make / POSIX shell).

Registered directly on the root app: ``up`` / ``down`` / ``migrate`` / ``logs``
/ ``ps``.
"""

from __future__ import annotations

import os
import subprocess

import typer

from intellisource.core.paths import project_root

_COMPOSE_FILE_PARTS = ("docker", "docker-compose.yml")


def _compose_args(*args: str) -> list[str]:
    """Build a ``docker compose -f <root>/docker/docker-compose.yml ...`` argv.

    Uses the v2 ``docker compose`` (space) form and an absolute compose-file
    path anchored at the project root, so it behaves identically from any CWD
    on Windows PowerShell, macOS, and Linux.
    """
    compose_file = project_root().joinpath(*_COMPOSE_FILE_PARTS)
    return ["docker", "compose", "-f", str(compose_file), *args]


def _git_sha() -> str:
    """Return the current HEAD commit sha, or ``"unknown"`` on any failure."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(project_root()),
            shell=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return "unknown"


def _run_compose(*args: str, env: dict[str, str] | None = None) -> None:
    """Run a docker compose subcommand, surfacing failures as a CLI exit code.

    ``shell=False`` with an argv list keeps the space-containing compose path
    safe on Windows PowerShell (no shell quoting of ``C:\\Program Files\\...``).
    """
    argv = _compose_args(*args)
    try:
        result = subprocess.run(argv, shell=False, env=env)  # noqa: S603
    except FileNotFoundError:
        typer.echo(
            "Error: 'docker' not found on PATH. Install Docker Desktop and retry."
        )
        raise typer.Exit(code=1) from None
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


def up(
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        "-r",
        help=(
            "Force --no-cache rebuild (use when src changed without a new commit sha)."
        ),
    ),
) -> None:
    """Start the full stack, injecting GIT_SHA to bust the src layer cache."""
    sha = _git_sha()
    env = {**os.environ, "GIT_SHA": sha}
    if rebuild:
        _run_compose("build", "--no-cache", env=env)
        _run_compose("up", "-d", "--wait", env=env)
    else:
        _run_compose("up", "-d", "--wait", "--build", env=env)


def down() -> None:
    """Stop and remove the stack containers."""
    _run_compose("down")


def migrate() -> None:
    """Run database migrations (alembic upgrade head) in a one-off container."""
    _run_compose("run", "--rm", "migrate")


def logs() -> None:
    """Follow logs from all stack services (Ctrl-C to stop)."""
    _run_compose("logs", "-f")


def ps() -> None:
    """Show status of the stack containers."""
    _run_compose("ps")


def register(app: typer.Typer) -> None:
    """Attach the stack lifecycle commands to the root *app*."""
    app.command("up")(up)
    app.command("down")(down)
    app.command("migrate")(migrate)
    app.command("logs")(logs)
    app.command("ps")(ps)
