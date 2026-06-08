"""Tool registry primitives.

Defines:
- ``AgentToolRegistry`` — register/lookup/filter/auto-discover tools.
- ``_atomic_tool_defs`` / ``_default_tool_defs`` — built-in tool definitions
  installed by ``register_atomic_tools`` / ``register_defaults``.

``PermissionLevel`` / ``ToolDefinition`` are defined in
:mod:`intellisource.agent.tools._spec` and re-exported here for callers that
import them from this module. The control-plane (management + run) tool
definitions are co-located with their execute functions and pulled in as
``MANAGEMENT_TOOL_DEFS`` / ``RUN_TOOL_DEFS``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Coroutine

from intellisource.agent.tools._spec import PermissionLevel, ToolDefinition
from intellisource.agent.tools.executes.atomic import ATOMIC_TOOL_DEFS
from intellisource.agent.tools.executes.collect import COLLECT_TOOL_DEF
from intellisource.agent.tools.executes.distribute import DISTRIBUTE_TOOL_DEF
from intellisource.agent.tools.executes.manage import MANAGEMENT_TOOL_DEFS
from intellisource.agent.tools.executes.process import PROCESS_TOOL_DEF
from intellisource.agent.tools.executes.run import RUN_TOOL_DEFS
from intellisource.agent.tools.executes.search_and_content import READ_TOOL_DEFS
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

__all__ = ["AgentToolRegistry", "PermissionLevel", "ToolDefinition"]

_DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parent


class AgentToolRegistry:
    """Registry of agent-callable tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        execute_fn: Callable[..., Coroutine[Any, Any, Any]],
        permission_level: PermissionLevel = PermissionLevel.auto,
        mutates_external_state: bool = False,
    ) -> None:
        """Register a tool definition."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            execute=execute_fn,
            permission_level=permission_level,
            mutates_external_state=mutates_external_state,
        )

    def register_defaults(self) -> None:
        """Register the six built-in tools."""
        defaults = _default_tool_defs()
        for defn in defaults:
            self._tools[defn.name] = defn

    def get(self, name: str) -> ToolDefinition | None:
        """Return tool by name, or None if not found."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return names of all registered tools."""
        return list(self._tools.keys())

    def register_atomic_tools(self) -> None:
        """Register all 10 atomic processing tools + llm_complete meta-tool."""
        defs = _atomic_tool_defs()
        for defn in defs:
            self._tools[defn.name] = defn

    def register_management_tools(self) -> None:
        """Register control-plane tools: CRUD for sources / subscriptions /
        pipelines plus pipeline run-trigger (``run_pipeline``) and run-status
        (``get_task_status``).

        Gated by each pipeline's ``tools_allowed`` — only elevated definitions
        such as ``admin-agent`` expose them; ``analyze`` agent mode auto-denies
        the mutating ones via ``mutates_external_state``.
        """
        for defn in _management_tool_defs():
            self._tools[defn.name] = defn

    def filter(
        self,
        *,
        allowed: list[str] | None = None,
        denied: list[str] | None = None,
    ) -> dict[str, ToolDefinition]:
        """Return a filtered subset of tools."""
        result = dict(self._tools)
        if allowed is not None:
            allowed_set = set(allowed)
            result = {k: v for k, v in result.items() if k in allowed_set}
        if denied is not None:
            denied_set = set(denied)
            result = {k: v for k, v in result.items() if k not in denied_set}
        return result

    def auto_discover(self, tools_dir: str | Path | None = None) -> None:
        """Scan tools_dir for plugin modules exporting TOOL_DEFINITION.

        Each *.py file (skipping __init__.py and dunder-prefixed names) is
        imported under a synthetic module name and inspected for a top-level
        TOOL_DEFINITION attribute of type ToolDefinition. Already-registered
        tool names take precedence (manual register wins over auto-discover).
        Import or attribute errors are logged at WARNING and skipped — they
        do not abort discovery of remaining files or application startup.
        """
        base = Path(tools_dir) if tools_dir is not None else _DEFAULT_PLUGINS_DIR
        if not base.is_dir():
            logger.warning(
                "auto_discover: tools_dir %s does not exist or is not a directory",
                base,
            )
            return

        for child in sorted(base.iterdir()):
            if not child.is_file() or child.suffix != ".py":
                continue
            if child.name.startswith("_"):
                continue

            module_name = f"intellisource.agent.tools._discovered.{child.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, str(child))
                if spec is None or spec.loader is None:
                    logger.warning("auto_discover: failed to build spec for %s", child)
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            except Exception as exc:
                logger.warning("auto_discover: import failed for %s: %s", child, exc)
                continue

            tool_def = getattr(module, "TOOL_DEFINITION", None)
            if tool_def is None:
                continue
            if not isinstance(tool_def, ToolDefinition):
                logger.warning(
                    "auto_discover: %s.TOOL_DEFINITION is not a ToolDefinition "
                    "(got %s); skipping",
                    child,
                    type(tool_def).__name__,
                )
                continue
            if tool_def.name in self._tools:
                continue
            self._tools[tool_def.name] = tool_def


def _atomic_tool_defs() -> list[ToolDefinition]:
    """Return the 10 atomic tool definitions + llm_complete meta-tool
    (co-located in ``executes.atomic``)."""
    return ATOMIC_TOOL_DEFS


def _default_tool_defs() -> list[ToolDefinition]:
    """Return the six built-in tool definitions (co-located in their modules)."""
    return [COLLECT_TOOL_DEF, PROCESS_TOOL_DEF, DISTRIBUTE_TOOL_DEF, *READ_TOOL_DEFS]


def _management_tool_defs() -> list[ToolDefinition]:
    """Control-plane tool definitions: CRUD (sources / subscriptions / pipelines
    / templates) co-located in ``executes.manage`` plus the run-trigger /
    run-status tools co-located in ``executes.run``."""
    return [*MANAGEMENT_TOOL_DEFS, *RUN_TOOL_DEFS]
