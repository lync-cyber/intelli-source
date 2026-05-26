"""Agent tools facade.

Public surface:
- ``PermissionLevel`` / ``ToolDefinition`` / ``AgentToolRegistry`` — defined
  in :mod:`intellisource.agent.tools.registry`.
- ``_collect_execute`` / ``_process_execute`` / ``_distribute_execute`` /
  ``_search_execute`` / ``_get_content_detail_execute`` /
  ``_summarize_for_user_execute`` / ``_llm_complete_execute`` — defined in
  :mod:`intellisource.agent.tools.executes` (re-exported here for callers
  that historically used ``from intellisource.agent.tools import ...``).
- ``load_pipeline_config`` / ``_PIPELINES_DIR`` — local config helper.
"""

from __future__ import annotations

from pathlib import Path

from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.tools.executes.collect import _collect_execute
from intellisource.agent.tools.executes.distribute import _distribute_execute
from intellisource.agent.tools.executes.llm import _llm_complete_execute
from intellisource.agent.tools.executes.process import _process_execute
from intellisource.agent.tools.executes.search_and_content import (
    _get_content_detail_execute,
    _search_execute,
    _summarize_for_user_execute,
)
from intellisource.agent.tools.registry import (
    AgentToolRegistry,
    PermissionLevel,
    ToolDefinition,
)

_PIPELINES_DIR = Path(__file__).resolve().parents[4] / "config" / "pipelines"

__all__ = [
    "AgentToolRegistry",
    "PermissionLevel",
    "ToolDefinition",
    "_PIPELINES_DIR",
    "_collect_execute",
    "_distribute_execute",
    "_get_content_detail_execute",
    "_llm_complete_execute",
    "_process_execute",
    "_search_execute",
    "_summarize_for_user_execute",
    "load_pipeline_config",
]


def load_pipeline_config(name: str) -> PipelineConfig:
    """Load a pipeline config YAML by name from the pipelines dir."""
    path = _PIPELINES_DIR / f"{name}.yaml"
    return PipelineConfig.from_yaml(str(path))
