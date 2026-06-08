"""Tool descriptor primitives shared by the registry and the execute modules.

Defines ``PermissionLevel`` and ``ToolDefinition``. They live here — rather than
in :mod:`intellisource.agent.tools.registry` — so that the per-domain execute
modules can build their own ``ToolDefinition`` lists without importing the
registry (which in turn imports those lists), avoiding an import cycle.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


class PermissionLevel(str, enum.Enum):
    """Tool invocation permission level.

    Values:
        auto: executed without confirmation (default for read-only tools).
        confirm: **confirm-as-logged** semantics — when invoked under
            ``run_flexible``, the runner records a ``pending_confirmation``
            event in 3 places (logger.info / tool_results entry / messages
            entry returned to the LLM) and skips actual execution for the
            current turn. The LLM observes the pending status via the next
            assistant turn and decides whether to retry, escalate or abort.
            **This is not a hard blocking-pause** — there is no callback
            wait or user-prompt loop in the runtime; production callers
            who need a true human-in-the-loop should subscribe to the
            ``pending_confirmation`` log event externally and re-issue
            the tool call with elevated permission once approved.
        deny: never executed; runner drops from tool descriptors at
            ``_filter_tools`` time and hard-rejects at runtime as a defence
            against LLM hallucination of denied tool names.
    """

    auto = "auto"
    confirm = "confirm"
    deny = "deny"


@dataclass
class ToolDefinition:
    """A single tool that can be invoked by the agent.

    Fields:
        mutates_external_state: True when the tool writes to a system the
            user can observe outside the agent (DB, message bus, webhook,
            outbound email, file system, etc.). Default False = read-only.
            ``analyze`` agent mode auto-denies tools where this is True so
            new side-effectful tools must opt in explicitly. Read-only tools
            (search/get/summarize) keep the default.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[..., Coroutine[Any, Any, Any]]
    permission_level: PermissionLevel = field(default=PermissionLevel.auto)
    mutates_external_state: bool = False
