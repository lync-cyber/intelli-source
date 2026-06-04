"""Agent tools facade.

Public surface:
- ``PermissionLevel`` / ``ToolDefinition`` / ``AgentToolRegistry`` — defined
  in :mod:`intellisource.agent.tools.registry`.
- ``_collect_execute`` / ``_process_execute`` / ``_distribute_execute`` /
  ``_search_execute`` / ``_get_content_detail_execute`` /
  ``_summarize_for_user_execute`` / ``_llm_complete_execute`` — defined in
  :mod:`intellisource.agent.tools.executes` (re-exported here for callers
  that historically used ``from intellisource.agent.tools import ...``).
"""

from __future__ import annotations

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

__all__ = [
    "AgentToolRegistry",
    "PermissionLevel",
    "ToolDefinition",
    "_collect_execute",
    "_distribute_execute",
    "_get_content_detail_execute",
    "_llm_complete_execute",
    "_process_execute",
    "_search_execute",
    "_summarize_for_user_execute",
]
