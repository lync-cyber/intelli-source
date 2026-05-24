"""FlexibleLoop — LLM agent loop with tool access and mode routing."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from intellisource.agent.tools import PermissionLevel, ToolDefinition
from intellisource.core.errors import ErrorCategory, IntelliSourceError

logger = logging.getLogger(__name__)

# Fallback set for callers that register tools without the
# `ToolDefinition.mutates_external_state` flag.
_ANALYZE_DENIED_TOOLS: frozenset[str] = frozenset({"distribute", "process"})


class FlexibleLoop:
    """Runs the LLM agent loop with tool access.

    Handles process / analyze / preview agent modes.
    """

    def __init__(
        self,
        tool_registry: Any,
        llm_gateway: Any,
        emit_pipeline_start: Callable[..., Coroutine[Any, Any, None]],
        emit_tool_call: Callable[..., Coroutine[Any, Any, None]],
        emit_llm_call: Callable[..., Coroutine[Any, Any, None]],
        emit_pipeline_error: Callable[..., Coroutine[Any, Any, None]],
        persist: Callable[..., Coroutine[Any, Any, dict[str, Any]]],
    ) -> None:
        self._tool_registry = tool_registry
        self._llm_gateway = llm_gateway
        self._emit_pipeline_start = emit_pipeline_start
        self._emit_tool_call = emit_tool_call
        self._emit_llm_call = emit_llm_call
        self._emit_pipeline_error = emit_pipeline_error
        self._persist = persist

    async def run(
        self,
        config: Any,
        user_message: str,
        session: dict[str, Any],
        *,
        agent_mode: Any,
        max_tokens_budget: int | None = None,
        tool_deps: Any = None,
    ) -> dict[str, Any]:
        """Run LLM agent loop with tool access."""
        chain_id = str(uuid.uuid4())
        await self._emit_pipeline_start(config.name, chain_id, "flexible")

        available_tools = self._filter_tools(config, agent_mode=agent_mode)
        tool_descriptors = self._build_tool_descriptors(available_tools)
        effective_budget = (
            max_tokens_budget
            if max_tokens_budget is not None
            else getattr(config, "max_tokens_budget", None)
        )

        steps_executed = 0
        tokens_used = 0
        budget_exhausted = False
        final_answer = ""
        messages: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        preview_plan: list[dict[str, Any]] = []

        sys_prompt = getattr(config, "system_prompt", None)
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})

        messages.extend(_session_messages(session))
        messages.append({"role": "user", "content": user_message})

        if effective_budget is not None and effective_budget <= 0:
            budget_exhausted = True

        if self._llm_gateway is None:
            msg = "LLM gateway is required for flexible mode"
            raise IntelliSourceError(msg, ErrorCategory.UNRECOVERABLE)

        while steps_executed < config.max_steps and not budget_exhausted:
            llm_t0 = time.monotonic()
            response = await self._llm_gateway.chat(
                messages=messages,
                tools=tool_descriptors,
            )
            llm_latency_ms = (time.monotonic() - llm_t0) * 1000.0
            steps_executed += 1

            usage = response.metadata.get("usage", {})
            tokens_used += usage.get("total_tokens", 0)
            budget_hit = (
                effective_budget is not None and tokens_used >= effective_budget
            )

            await self._emit_llm_call(
                config.name,
                chain_id,
                str(response.metadata.get("model", "")),
                int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
                int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
                llm_latency_ms,
            )

            tool_calls = response.metadata.get("tool_calls") or []
            finish_reason = response.metadata.get("finish_reason", "")
            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [_serialize_tool_call(tc) for tc in tool_calls],
                    }
                )
            elif response.content:
                final_answer = response.content

            if budget_hit:
                budget_exhausted = True
                break

            done = finish_reason == "stop" or not tool_calls
            if done:
                break

            pipeline_perms: dict[str, str] = (
                getattr(config, "tool_permissions", {}) or {}
            )

            for tc in tool_calls:
                tc_name, tc_id, tc_args = _parse_tool_call(tc)

                _override = pipeline_perms.get(tc_name)
                if _override is not None:
                    _effective_perm = PermissionLevel(_override)
                else:
                    _tool_raw_perm = self._tool_registry.get(tc_name)
                    _effective_perm = (
                        _tool_raw_perm.permission_level
                        if isinstance(_tool_raw_perm, ToolDefinition)
                        else PermissionLevel.auto
                    )
                if _effective_perm is PermissionLevel.deny:
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                {"status": "denied_by_permission", "tool": tc_name}
                            ),
                            "tool_call_id": tc_id,
                        }
                    )
                    tool_results.append(
                        {
                            "tool": tc_name,
                            "status": "denied_by_permission",
                            "output": None,
                        }
                    )
                    continue

                if self._is_analyze_denied(tc_name, agent_mode):
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                {"status": "denied_by_analyze_mode", "tool": tc_name}
                            ),
                            "tool_call_id": tc_id,
                        }
                    )
                    tool_results.append(
                        {
                            "tool": tc_name,
                            "output": None,
                            "denied": True,
                            "reason": "analyze_mode",
                        }
                    )
                    continue

                if _is_preview_mode(agent_mode):
                    preview_plan.append(
                        {
                            "tool": tc_name,
                            "args": tc_args,
                            "would_execute_at": datetime.now(
                                tz=timezone.utc
                            ).isoformat(),
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps({"status": "preview_skipped"}),
                            "tool_call_id": tc_id,
                        }
                    )
                    continue

                if _effective_perm is PermissionLevel.confirm:
                    logger.info(
                        "pending_confirmation",
                        extra={
                            "tool": tc_name,
                            "args": tc_args,
                            "tool_call_id": tc_id,
                        },
                    )
                    tool_results.append(
                        {
                            "tool": tc_name,
                            "status": "pending_confirmation",
                            "args": tc_args,
                            "tool_call_id": tc_id,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                {"status": "pending_confirmation", "tool": tc_name}
                            ),
                            "tool_call_id": tc_id,
                        }
                    )
                    continue

                if tool_deps is not None:
                    tc_args = {**tc_args, "tool_deps": tool_deps}
                tool_raw = self._tool_registry.get(tc_name)
                if tool_raw is not None:
                    tool_fn = _resolve_callable(tool_raw)
                    tool_t0 = time.monotonic()
                    try:
                        result = await tool_fn(**tc_args)

                        await self._emit_tool_call(
                            config.name,
                            chain_id,
                            tc_name,
                            (time.monotonic() - tool_t0) * 1000.0,
                            "success",
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "content": json.dumps(result, default=str),
                                "tool_call_id": tc_id,
                            }
                        )
                        tool_results.append({"tool": tc_name, "output": result})
                    except Exception as exc:
                        logger.warning("Tool %s failed: %s", tc_name, exc)
                        await self._emit_tool_call(
                            config.name,
                            chain_id,
                            tc_name,
                            (time.monotonic() - tool_t0) * 1000.0,
                            "error",
                            error=str(exc),
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "content": f"Error: {exc}",
                                "tool_call_id": tc_id,
                            }
                        )
                        tool_results.append(
                            {
                                "tool": tc_name,
                                "output": None,
                                "error": str(exc),
                            }
                        )
                else:
                    logger.warning("Unknown tool requested by LLM: %s", tc_name)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": tc_name,
                            "content": json.dumps(
                                {"error": "unknown_tool", "name": tc_name}
                            ),
                        }
                    )
                    tool_results.append(
                        {
                            "tool": tc_name,
                            "output": None,
                            "error": "unknown_tool",
                        }
                    )

        if _is_preview_mode(agent_mode):
            persist_result = await self._persist(
                status="preview",
                steps_executed=steps_executed,
                results=tool_results,
                pipeline_name=config.name,
                execution_mode="flexible",
                task_chain_id=chain_id,
            )
            persist_result["plan"] = preview_plan
            persist_result["tokens_used"] = tokens_used
            return persist_result

        persist_result = await self._persist(
            status="success",
            steps_executed=steps_executed,
            results=tool_results,
            pipeline_name=config.name,
            execution_mode="flexible",
            task_chain_id=chain_id,
        )
        if budget_exhausted:
            persist_result["budget_exhausted"] = True
        persist_result["tokens_used"] = tokens_used
        if final_answer:
            persist_result["final_answer"] = final_answer
        return persist_result

    def _filter_tools(
        self,
        config: Any,
        agent_mode: Any,
    ) -> list[str]:
        """Build available tool list respecting config filters and permission levels."""
        all_tools: list[str] = self._tool_registry.list_tools()
        denied = set(config.tools_denied)
        allowed = set(config.tools_allowed)

        if _is_analyze_mode(agent_mode):
            denied = denied | self._analyze_denied_tools(all_tools)

        if allowed:
            tools = [t for t in all_tools if t in allowed]
        else:
            tools = list(all_tools)

        pipeline_perms: dict[str, str] = getattr(config, "tool_permissions", {}) or {}
        permission_denied: set[str] = set()
        for t in tools:
            override = pipeline_perms.get(t)
            if override is not None:
                effective = PermissionLevel(override)
            else:
                tool_def = self._tool_registry.get(t)
                effective = (
                    tool_def.permission_level
                    if isinstance(tool_def, ToolDefinition)
                    else PermissionLevel.auto
                )
            if effective is PermissionLevel.deny:
                permission_denied.add(t)

        return [t for t in tools if t not in denied and t not in permission_denied]

    def _analyze_denied_tools(self, candidate_names: list[str]) -> set[str]:
        return {n for n in candidate_names if self._is_analyze_denied_name(n)}

    def _is_analyze_denied_name(self, name: str) -> bool:
        tool_def = self._tool_registry.get(name)
        if isinstance(tool_def, ToolDefinition) and tool_def.mutates_external_state:
            return True
        return name in _ANALYZE_DENIED_TOOLS

    def _is_analyze_denied(self, name: str, agent_mode: Any) -> bool:
        """Return True when name is denied under analyze mode."""
        if not _is_analyze_mode(agent_mode):
            return False
        return self._is_analyze_denied_name(name)

    def _build_tool_descriptors(self, tool_names: list[str]) -> list[dict[str, Any]]:
        """Build OpenAI-style function tool descriptors."""
        descriptors: list[dict[str, Any]] = []
        for name in tool_names:
            tool = self._tool_registry.get(name)
            if isinstance(tool, ToolDefinition):
                description = tool.description
                parameters = tool.parameters
            else:
                description = ""
                parameters = {"type": "object", "properties": {}}
            descriptors.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
        return descriptors


def _resolve_callable(tool: Any) -> Any:
    """Unwrap ToolDefinition to its execute callable if needed."""
    if isinstance(tool, ToolDefinition):
        return tool.execute
    return tool


def _is_analyze_mode(agent_mode: Any) -> bool:
    """Return True when agent_mode represents analyze."""
    # AgentMode is str-enum; .value works for enum instances and raw strings.
    val = agent_mode.value if hasattr(agent_mode, "value") else str(agent_mode)
    return val == "analyze"


def _is_preview_mode(agent_mode: Any) -> bool:
    """Return True when agent_mode represents preview."""
    val = agent_mode.value if hasattr(agent_mode, "value") else str(agent_mode)
    return val == "preview"


def _serialize_tool_call(tool_call: Any) -> dict[str, Any]:
    """Return an assistant-message tool_call payload for LLM continuity."""
    name, call_id, args = _parse_tool_call(tool_call)
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args, default=str),
        },
    }


def _parse_tool_call(tool_call: Any) -> tuple[str, str, dict[str, Any]]:
    """Extract (name, id, arguments) from SDK-style or dict tool calls."""
    if hasattr(tool_call, "function"):
        name = str(tool_call.function.name)
        call_id = str(getattr(tool_call, "id", ""))
        raw_args = tool_call.function.arguments or "{}"
    elif isinstance(tool_call, dict) and isinstance(tool_call.get("function"), dict):
        function = tool_call["function"]
        name = str(function["name"])
        call_id = str(tool_call.get("id", ""))
        raw_args = function.get("arguments", {})
    else:
        name = str(tool_call["name"])
        call_id = str(tool_call.get("id", ""))
        raw_args = tool_call.get("arguments", {})

    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            parsed = {}
    else:
        parsed = raw_args
    return name, call_id, parsed if isinstance(parsed, dict) else {}


def _session_messages(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Return valid prior conversation messages from a session payload."""
    raw_messages = session.get("messages")
    if not isinstance(raw_messages, list):
        return []
    messages: list[dict[str, Any]] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant", "tool"} and isinstance(content, str):
            messages.append({"role": role, "content": content})
    return messages
