"""Shared utilities for extracting user-visible answers from AgentRunner results."""

from __future__ import annotations

from typing import Any


def extract_answer(result: dict[str, Any]) -> str:
    """Return the best assistant-facing text from flexible-mode tool results."""
    final_answer = result.get("final_answer")
    if final_answer:
        return str(final_answer)
    for step in reversed(result.get("results", [])):
        output = step.get("output", {})
        if not isinstance(output, dict):
            continue
        for key in ("summary", "text", "content"):
            value = output.get(key)
            if value:
                return str(value)
    return ""
