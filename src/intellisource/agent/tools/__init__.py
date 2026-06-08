"""Agent tools facade.

Stable public surface:
- ``AgentToolRegistry`` / ``PermissionLevel`` / ``ToolDefinition`` — the
  recommended entry point. External transport adapters (``api.routers`` /
  ``mcp_server``) are barred by importlinter Contracts 10/11 from importing
  ``executes`` directly and must obtain tools through ``AgentToolRegistry``.
  ``PermissionLevel`` / ``ToolDefinition`` are defined in
  :mod:`intellisource.agent.tools._spec` and re-exported via
  :mod:`intellisource.agent.tools.registry`.

Frozen legacy compat shim (do not extend):
- The seven ``_*_execute`` names below are re-exported only for historical
  callers that used ``from intellisource.agent.tools import _collect_execute``.
  New code imports execute functions from
  ``intellisource.agent.tools.executes.<module>``; the management / run /
  ``summarize_cluster`` execute functions are intentionally *not* surfaced here.
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
