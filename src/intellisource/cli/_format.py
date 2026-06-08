"""Human-readable output formatting for CLI results."""

from __future__ import annotations

import json
from typing import Any

import typer


def emit(data: dict[str, Any], *, json_output: bool) -> None:
    """Output *data* as JSON or a human-readable table."""
    if json_output:
        typer.echo(json.dumps(data))
    else:
        typer.echo(format_table(data))


def format_table(data: dict[str, Any] | list[dict[str, Any]]) -> str:
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


def format_detail(data: dict[str, Any]) -> str:
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


def format_diff(data: dict[str, Any]) -> str:
    """Render a yaml↔DB config diff (what a reload would change)."""
    action = str(data.get("db_only_action", "change")).upper()
    return "\n".join(
        [
            f"yaml-only (reload will CREATE): {data.get('yaml_only', [])}",
            f"db-only   (reload will {action}): {data.get('db_only', [])}",
            f"in-both   (reload will UPDATE): {data.get('both', [])}",
        ]
    )
