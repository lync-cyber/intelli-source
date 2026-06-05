"""Helpers for strict/batch pipeline step parameter merging."""

from __future__ import annotations

from typing import Any

from intellisource.agent.deps import ToolDeps
from intellisource.config.pipeline_models import StepSpec


def merge_step_output(
    tool_name: str, output: Any, step_context: dict[str, Any]
) -> None:
    """Merge a tool step output into the rolling step_context dict."""
    if not isinstance(output, dict):
        return
    if tool_name == "collect":
        raw_ids = output.get("raw_content_ids") or []
        content_id = output.get("content_id") or (raw_ids[0] if raw_ids else None)
        if content_id:
            step_context["content_id"] = content_id
        if raw_ids:
            step_context["raw_content_ids"] = raw_ids
        source_id = output.get("source_id")
        if source_id:
            step_context["source_id"] = source_id
        source_type = output.get("source_type")
        if source_type:
            step_context["source_type"] = source_type
        return
    if tool_name == "process":
        # ``result`` is a list when several contents are processed in one run,
        # so the processed ids live at the top level — distribute fans out over
        # the full list and falls back to ``content_id`` for the single case.
        processed_ids = output.get("processed_content_ids") or []
        if processed_ids:
            step_context["processed_content_ids"] = processed_ids
        inner = output.get("result")
        inner_dict = inner if isinstance(inner, dict) else {}
        content_id = output.get("content_id") or inner_dict.get("content_id")
        if content_id:
            step_context["content_id"] = content_id
        raw_id = inner_dict.get("raw_content_id")
        if raw_id:
            step_context["raw_content_id"] = raw_id
        return
    if tool_name == "distribute":
        inner = output.get("result")
        if isinstance(inner, dict) and inner.get("content_id"):
            step_context["content_id"] = inner["content_id"]


def build_step_params(
    step: StepSpec,
    *,
    runtime_params: dict[str, Any],
    step_context: dict[str, Any],
    tool_deps: ToolDeps | None,
) -> dict[str, Any]:
    """Merge YAML params, Celery runtime params, and prior step outputs."""
    yaml_params = dict(step.get("params") or {})
    merged: dict[str, Any] = {**yaml_params, **runtime_params, **step_context}
    if tool_deps is not None:
        merged["tool_deps"] = tool_deps
    return merged
