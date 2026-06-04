"""Response schemas for the pipelines router."""

from __future__ import annotations

from typing import Any

from intellisource.api.schemas.common import APIModel


class PipelineSummary(APIModel):
    """Compact pipeline-definition listing (mirrors `list_summaries`)."""

    name: str
    mode: str
    max_steps: int
    tools_allowed: list[str] = []


class PipelineDetail(APIModel):
    """Full pipeline definition (mirrors `_pipeline_to_dict`)."""

    name: str
    mode: str
    max_steps: int
    on_failure: str
    steps: list[dict[str, Any]] = []
    tools_allowed: list[str] = []
    tools_denied: list[str] = []
    system_prompt: str | None = None
    agent_mode: str | None = None
    max_tokens_budget: int | None = None
    tool_permissions: dict[str, str] = {}


class PipelineRunResponse(APIModel):
    """Dispatch result for POST /pipelines/{name}/run."""

    task_id: str
