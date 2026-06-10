"""FlexibleLoop — LLM agent loop with tool access and mode routing."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Coroutine

from intellisource.agent.deps import ToolDeps
from intellisource.agent.executors.strict import _resolve_callable
from intellisource.agent.observer import LoopObserver
from intellisource.agent.response_utils import extract_answer
from intellisource.agent.tool_gating import ToolPermissionResolver, _is_preview_mode
from intellisource.agent.tools import PermissionLevel, ToolDefinition
from intellisource.config.constants import (
    DEFAULT_LLM_TIMEOUT_S as _DEFAULT_LLM_TIMEOUT_S,
)
from intellisource.config.constants import (
    DEFAULT_TOOL_TIMEOUT_S as _DEFAULT_TOOL_TIMEOUT_S,
)
from intellisource.core.errors import ErrorCategory, IntelliSourceError
from intellisource.llm.prompts import load_prompt
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


def _default_system_prompt() -> str:
    """Render the flexible agent's identity system prompt from templates.

    Used by both ``run`` and ``run_stream`` as the fallback when a pipeline
    declares no ``system_prompt``: without an identity message the model drifts
    to a generic assistant persona (e.g. ``我是你的智能助手``). The callable
    tools reach the model through the ``tools=`` request param, so they are not
    duplicated into the prompt text.
    """
    return load_prompt("flexible_agent_system")


class FlexibleLoop:
    """Runs the LLM agent loop with tool access.

    Handles process / analyze / preview agent modes.
    """

    def __init__(
        self,
        tool_registry: Any,
        llm_gateway: Any,
        observer: LoopObserver,
        persist: Callable[..., Coroutine[Any, Any, dict[str, Any]]],
    ) -> None:
        self._tool_registry = tool_registry
        self._llm_gateway = llm_gateway
        self._observer = observer
        self._persist = persist
        self._tool_perms = ToolPermissionResolver(tool_registry)

    async def run(
        self,
        config: Any,
        user_message: str,
        session: dict[str, Any],
        *,
        agent_mode: Any,
        max_tokens_budget: int | None = None,
        tool_deps: ToolDeps | None = None,
        approved_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run the LLM agent loop with tool access and return the persist payload.

        ``approved_calls`` carries human-in-the-loop confirmed tool calls
        (tool + args) recovered from a confirm token: they are executed up
        front and seeded into the history so the next LLM turn summarises the
        result, letting a confirm-gated action (e.g. distribute) actually run.
        """
        result: dict[str, Any] = {}
        async for event in self._drive(
            config,
            user_message,
            session,
            agent_mode=agent_mode,
            max_tokens_budget=max_tokens_budget,
            tool_deps=tool_deps,
            approved_calls=approved_calls,
            stream=False,
        ):
            if event["type"] in ("done", "error"):
                result = event["metadata"]
        return result

    async def run_stream(
        self,
        config: Any,
        user_message: str,
        session: dict[str, Any],
        *,
        agent_mode: Any,
        max_tokens_budget: int | None = None,
        tool_deps: ToolDeps | None = None,
        approved_calls: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Streaming counterpart to ``run``, yielding SSE-shaped event dicts.

        Drives the same tool loop as ``run`` but each turn streams through
        ``stream_complete(tools=...)``: content deltas surface as ``token``
        events live, and the turn's accumulated tool_calls drive the loop, so a
        turn that ends in a final answer streams that answer directly (no extra
        LLM call). Event shape::

          {"type": "step", "step": int, "action": "llm_call"|"tool_call",
           "tool": str|None, "duration_ms": float, "status": str}
          {"type": "sources", "items": list[dict]}
          {"type": "token", "delta": str}
          {"type": "done", "metadata": {...persist payload..., final_answer, ...}}
          {"type": "error", "detail": str}
        """
        async for event in self._drive(
            config,
            user_message,
            session,
            agent_mode=agent_mode,
            max_tokens_budget=max_tokens_budget,
            tool_deps=tool_deps,
            approved_calls=approved_calls,
            stream=True,
        ):
            yield event

    async def _drive(
        self,
        config: Any,
        user_message: str,
        session: dict[str, Any],
        *,
        agent_mode: Any,
        max_tokens_budget: int | None,
        tool_deps: ToolDeps | None,
        approved_calls: list[dict[str, Any]] | None,
        stream: bool,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Shared agent loop backing both ``run`` and ``run_stream``.

        ``stream`` selects the per-turn LLM strategy (``_run_turn``) and whether
        ``step`` / ``sources`` / ``token`` events are emitted; permission
        gating, tool execution, budget accounting and persistence are identical
        for both. Always ends by yielding a single ``done`` (or ``error``)
        event whose metadata is the persist payload.
        """
        chain_id = str(uuid.uuid4())
        mode_label = "flexible-stream" if stream else "flexible"
        await self._observer.pipeline_start(config.name, chain_id, mode_label)

        available_tools = self._tool_perms.filter_tools(config, agent_mode)
        tool_descriptors = self._tool_perms.build_tool_descriptors(available_tools)
        effective_budget = (
            max_tokens_budget
            if max_tokens_budget is not None
            else getattr(config, "max_tokens_budget", None)
        )

        steps_executed = 0
        tokens_used = 0
        budget_exhausted = False
        final_answer = ""
        turn_error: str | None = None
        messages: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        preview_plan: list[dict[str, Any]] = []
        sources_yielded = False
        preview = _is_preview_mode(agent_mode)

        if stream and preview:
            msg = "preview agent_mode is not supported by run_stream"
            raise IntelliSourceError(msg, ErrorCategory.UNRECOVERABLE)

        # Fall back to the identity+tools prompt so the agent keeps the
        # IntelliSource persona instead of drifting to a generic model identity.
        sys_prompt = getattr(config, "system_prompt", None) or _default_system_prompt()
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})

        messages.extend(_session_messages(session))
        messages.append({"role": "user", "content": user_message})

        if effective_budget is not None and effective_budget <= 0:
            budget_exhausted = True

        if self._llm_gateway is None:
            msg = "LLM gateway is required for flexible mode"
            raise IntelliSourceError(msg, ErrorCategory.UNRECOVERABLE)

        if approved_calls:
            async for event in self._execute_approved_calls(
                approved_calls,
                config=config,
                chain_id=chain_id,
                tool_deps=tool_deps,
                messages=messages,
                tool_results=tool_results,
                agent_mode=agent_mode,
            ):
                if stream:
                    yield event

        # Track a running token estimate so the per-turn compaction check skips
        # re-scanning the whole history every loop; only the newly appended tail
        # is re-estimated, and a real compaction recomputes from the new shape.
        accounted_len = len(messages)
        history_tokens = self._estimate_history_tokens(messages)

        while steps_executed < config.max_steps and not budget_exhausted:
            # Fold the previous turn's appended tail into the running estimate,
            # then summarise old turns before the turn so a long tool-heavy run
            # stays inside the context window. The estimate is handed to the
            # compactor as precomputed_total; the compressor preserves pairing.
            if history_tokens is not None and len(messages) > accounted_len:
                delta = self._estimate_history_tokens(messages[accounted_len:])
                if delta is not None:
                    history_tokens += delta
            accounted_len = len(messages)

            pre_compress_len = len(messages)
            messages = await self._compress_history(
                messages, precomputed_total=history_tokens
            )
            if len(messages) != pre_compress_len:
                history_tokens = self._estimate_history_tokens(messages)
                accounted_len = len(messages)

            history_problems = _validate_history(messages)
            if history_problems:
                logger.warning("history invariant violations: %s", history_problems)
            turn: dict[str, Any] = {}
            async for ev in self._run_turn(
                messages, tool_descriptors, config, stream=stream
            ):
                if ev.get("_turn"):
                    turn = ev
                else:
                    yield ev
            steps_executed += 1

            if turn.get("error"):
                turn_error = str(turn["error"])
                break

            tokens_used += int(turn.get("tokens", 0) or 0)
            budget_hit = (
                effective_budget is not None and tokens_used >= effective_budget
            )

            await self._observer.llm_call(
                config.name,
                chain_id,
                str(turn.get("model", "")),
                int(turn.get("prompt_tokens", 0) or 0),
                int(turn.get("completion_tokens", 0) or 0),
                float(turn.get("latency_ms", 0.0) or 0.0),
            )
            if stream:
                yield {
                    "type": "step",
                    "step": steps_executed,
                    "action": "llm_call",
                    "tool": None,
                    "duration_ms": turn.get("latency_ms", 0.0),
                    "status": "success",
                }

            tool_calls = turn.get("tool_calls") or []
            content = turn.get("content", "")
            if tool_calls:
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": content or "",
                    "tool_calls": [_serialize_tool_call(tc) for tc in tool_calls],
                }
                rc = turn.get("reasoning_content")
                if rc:
                    assistant_msg["reasoning_content"] = rc
                messages.append(assistant_msg)
            elif content:
                final_answer = content

            if budget_hit:
                budget_exhausted = True
                break

            # Terminate only when the model requested no tools. A contradictory
            # ``finish_reason == "stop"`` alongside pending tool_calls must still
            # run them, else the assistant tool_calls message just appended would
            # be left with no matching tool responses (malformed history).
            if not tool_calls:
                break

            pipeline_perms: dict[str, str] = (
                getattr(config, "tool_permissions", {}) or {}
            )

            # Phase 1: resolve each tool_call to an ordered action. Gating
            # (deny / analyze / preview / confirm / unknown) carries its own
            # messages; auto-permitted calls are queued to run concurrently.
            actions: list[dict[str, Any]] = []
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
                    actions.append(
                        {
                            "kind": "gated",
                            "message": {
                                "role": "tool",
                                "content": json.dumps(
                                    {"status": "denied_by_permission", "tool": tc_name}
                                ),
                                "tool_call_id": tc_id,
                            },
                            "tool_result": {
                                "tool": tc_name,
                                "status": "denied_by_permission",
                                "output": None,
                            },
                        }
                    )
                    continue

                if self._tool_perms.is_analyze_denied(tc_name, agent_mode):
                    actions.append(
                        {
                            "kind": "gated",
                            "message": {
                                "role": "tool",
                                "content": json.dumps(
                                    {
                                        "status": "denied_by_analyze_mode",
                                        "tool": tc_name,
                                    }
                                ),
                                "tool_call_id": tc_id,
                            },
                            "tool_result": {
                                "tool": tc_name,
                                "output": None,
                                "denied": True,
                                "reason": "analyze_mode",
                            },
                        }
                    )
                    continue

                if preview:
                    actions.append(
                        {
                            "kind": "gated",
                            "preview_entry": {
                                "tool": tc_name,
                                "args": tc_args,
                                "would_execute_at": datetime.now(
                                    tz=timezone.utc
                                ).isoformat(),
                            },
                            "message": {
                                "role": "tool",
                                "content": json.dumps({"status": "preview_skipped"}),
                                "tool_call_id": tc_id,
                            },
                        }
                    )
                    continue

                if _effective_perm is PermissionLevel.confirm:
                    logger.info(
                        "pending_confirmation",
                        extra={
                            "tool": tc_name,
                            "tool_args": tc_args,
                            "tool_call_id": tc_id,
                        },
                    )
                    actions.append(
                        {
                            "kind": "gated",
                            "tool_result": {
                                "tool": tc_name,
                                "status": "pending_confirmation",
                                "args": tc_args,
                                "tool_call_id": tc_id,
                            },
                            "message": {
                                "role": "tool",
                                "content": json.dumps(
                                    {"status": "pending_confirmation", "tool": tc_name}
                                ),
                                "tool_call_id": tc_id,
                            },
                        }
                    )
                    continue

                if tool_deps is not None:
                    tc_args = {**tc_args, "tool_deps": tool_deps}
                tool_raw = self._tool_registry.get(tc_name)
                if tool_raw is not None:
                    actions.append(
                        {
                            "kind": "run",
                            "name": tc_name,
                            "id": tc_id,
                            "args": tc_args,
                            "fn": _resolve_callable(tool_raw),
                        }
                    )
                else:
                    logger.warning("Unknown tool requested by LLM: %s", tc_name)
                    actions.append(
                        {
                            "kind": "gated",
                            "message": {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": tc_name,
                                "content": json.dumps(
                                    {"error": "unknown_tool", "name": tc_name}
                                ),
                            },
                            "tool_result": {
                                "tool": tc_name,
                                "output": None,
                                "error": "unknown_tool",
                            },
                        }
                    )

            # Phase 2: run the auto-permitted calls concurrently — independent
            # tools in one turn no longer wait on each other.
            run_actions = [a for a in actions if a["kind"] == "run"]
            outcomes = await asyncio.gather(
                *(
                    self._execute_one_tool(
                        config, a["name"], a["id"], a["args"], a["fn"]
                    )
                    for a in run_actions
                )
            )
            outcome_iter = iter(outcomes)

            # Phase 3: apply outcomes in original tool_call order — append
            # messages / results, emit observer + stream events, surface sources.
            for action in actions:
                if action["kind"] == "gated":
                    preview_entry = action.get("preview_entry")
                    if preview_entry is not None:
                        preview_plan.append(preview_entry)
                    messages.append(action["message"])
                    tool_result = action.get("tool_result")
                    if tool_result is not None:
                        tool_results.append(tool_result)
                    continue

                outcome = next(outcome_iter)
                tc_name = outcome["name"]
                tc_id = outcome["id"]
                duration_ms = outcome["duration_ms"]
                if outcome["ok"]:
                    result = outcome["result"]
                    await self._observer.tool_call(
                        config.name, chain_id, tc_name, duration_ms, "success"
                    )
                    if stream:
                        yield {
                            "type": "step",
                            "step": steps_executed,
                            "action": "tool_call",
                            "tool": tc_name,
                            "duration_ms": duration_ms,
                            "status": "success",
                        }
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(result, default=str),
                            "tool_call_id": tc_id,
                        }
                    )
                    tool_results.append({"tool": tc_name, "output": result})

                    if (
                        stream
                        and not sources_yielded
                        and tc_name == "search"
                        and isinstance(result, dict)
                    ):
                        sources = _extract_search_sources(result)
                        if sources:
                            yield {"type": "sources", "items": sources}
                            sources_yielded = True
                else:
                    exc = outcome["exc"]
                    await self._observer.tool_call(
                        config.name,
                        chain_id,
                        tc_name,
                        duration_ms,
                        "error",
                        error=str(exc),
                    )
                    if stream:
                        yield {
                            "type": "step",
                            "step": steps_executed,
                            "action": "tool_call",
                            "tool": tc_name,
                            "duration_ms": duration_ms,
                            "status": "error",
                            "error": str(exc),
                        }
                    messages.append(
                        {
                            "role": "tool",
                            "content": _tool_error_payload(tc_name, exc),
                            "tool_call_id": tc_id,
                        }
                    )
                    tool_results.append(
                        {
                            "tool": tc_name,
                            "output": None,
                            "error": _describe_exc(exc),
                        }
                    )

        # A model can answer through a tool (e.g. summarize_for_user) and then
        # stream no free text; recover that tool-borne answer so a stream client
        # never sees an empty reply.
        if stream and not final_answer and turn_error is None and not budget_exhausted:
            fallback = extract_answer({"results": tool_results})
            if fallback:
                final_answer = fallback
                yield {"type": "token", "delta": fallback}

        if preview:
            persist_result = await self._persist(
                status="preview",
                steps_executed=steps_executed,
                results=tool_results,
                pipeline_name=config.name,
                execution_mode=mode_label,
                task_chain_id=chain_id,
            )
            persist_result["plan"] = preview_plan
            persist_result["tokens_used"] = tokens_used
            yield {"type": "done", "metadata": persist_result}
            return

        persist_result = await self._persist(
            status="success" if turn_error is None else "error",
            steps_executed=steps_executed,
            results=tool_results,
            pipeline_name=config.name,
            execution_mode=mode_label,
            task_chain_id=chain_id,
        )
        if budget_exhausted:
            persist_result["budget_exhausted"] = True
        persist_result["tokens_used"] = tokens_used
        if final_answer:
            persist_result["final_answer"] = final_answer

        if turn_error is not None:
            persist_result["detail"] = turn_error
            await self._observer.pipeline_error(config.name, chain_id, turn_error)
            yield {"type": "error", "detail": turn_error, "metadata": persist_result}
        else:
            yield {"type": "done", "metadata": persist_result}

    async def _compress_history(
        self,
        messages: list[dict[str, Any]],
        precomputed_total: int | None = None,
    ) -> list[dict[str, Any]]:
        """Best-effort history compaction via the gateway; never breaks the loop.

        The gateway is duck-typed (real / mock / None), so a missing,
        non-awaitable, or raising ``compress_if_needed`` degrades to the
        original messages instead of propagating. ``precomputed_total`` is the
        loop's running token estimate, letting the compactor skip a full rescan.
        """
        compress = getattr(self._llm_gateway, "compress_if_needed", None)
        if compress is None:
            return messages
        try:
            result = compress(
                messages, task_type="chat", precomputed_total=precomputed_total
            )
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            logger.warning("history compression skipped: %s", exc)
            return messages
        return result if isinstance(result, list) else messages

    def _estimate_history_tokens(self, messages: list[dict[str, Any]]) -> int | None:
        """Running token estimate via the gateway, or None when unavailable.

        Mirrors the gateway's own estimate basis so the value can be fed back as
        ``precomputed_total``; a gateway lacking the method (mock / None) yields
        None and the compactor falls back to its own per-call scan.
        """
        estimate = getattr(self._llm_gateway, "estimate_history_tokens", None)
        if estimate is None:
            return None
        try:
            return int(estimate(messages))
        except Exception as exc:  # noqa: BLE001
            logger.warning("history token estimate skipped: %s", exc)
            return None

    async def _execute_one_tool(
        self,
        config: Any,
        tc_name: str,
        tc_id: str,
        tc_args: dict[str, Any],
        tool_fn: Any,
    ) -> dict[str, Any]:
        """Execute one resolved tool call and return a structured outcome.

        Never raises: a tool error or per-call timeout becomes an ``ok: False``
        outcome. Pure tool IO — no message/result mutation or event emission — so
        many independent calls in one turn can run concurrently and have their
        outcomes applied afterwards in the original tool_call order. The callable
        is resolved once at gating time and passed in, so the registry is read
        exactly once per call.
        """
        t0 = time.monotonic()
        timeout = _normalize_timeout(
            getattr(config, "tool_timeout_s", _DEFAULT_TOOL_TIMEOUT_S)
        )
        try:
            result = await asyncio.wait_for(tool_fn(**tc_args), timeout=timeout)
            return {
                "name": tc_name,
                "id": tc_id,
                "ok": True,
                "result": result,
                "duration_ms": (time.monotonic() - t0) * 1000.0,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool %s failed: %s", tc_name, exc)
            return {
                "name": tc_name,
                "id": tc_id,
                "ok": False,
                "exc": exc,
                "duration_ms": (time.monotonic() - t0) * 1000.0,
            }

    async def _run_turn(
        self,
        messages: list[dict[str, Any]],
        tool_descriptors: list[dict[str, Any]],
        config: Any,
        *,
        stream: bool,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run one LLM turn, yielding ``token`` events then a ``_turn`` summary.

        Streaming mode runs through ``stream_complete(tools=...)``: content
        deltas are yielded as ``token`` events and the accumulated tool_calls /
        finish_reason arrive in the terminal chunk's metadata, so the turn that
        ends in a final answer streams it directly. Non-streaming mode runs
        through the cached ``chat`` call. Both finish by yielding a single
        ``{"_turn": True, ...}`` dict — consumed by ``_drive`` and never
        forwarded to callers — carrying content, tool_calls, finish_reason,
        token counts, latency, model and any error.
        """
        llm_t0 = time.monotonic()
        llm_timeout = _normalize_timeout(
            getattr(config, "llm_timeout_s", _DEFAULT_LLM_TIMEOUT_S)
        )
        if stream:
            content = ""
            tool_calls: Any = None
            finish_reason = ""
            prompt_tokens = 0
            completion_tokens = 0
            model = ""
            error: str | None = None
            # Time each upstream chunk read independently (a per-read deadline,
            # not a whole-turn one) so a stalled stream is cut without penalising
            # a long but healthy one, and our own ``yield`` backpressure between
            # chunks never counts against the deadline.
            stream_gen = self._llm_gateway.stream_complete(
                messages=messages, tools=tool_descriptors
            )
            try:
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            stream_gen.__anext__(), timeout=llm_timeout
                        )
                    except StopAsyncIteration:
                        break
                    if chunk.get("done"):
                        meta = chunk.get("metadata") or {}
                        prompt_tokens = int(meta.get("input_tokens", 0) or 0)
                        completion_tokens = int(meta.get("output_tokens", 0) or 0)
                        tool_calls = meta.get("tool_calls")
                        finish_reason = str(meta.get("finish_reason", "") or "")
                        model = str(meta.get("model", "") or "")
                        break
                    delta = chunk.get("content", "")
                    if delta:
                        content += delta
                        yield {"type": "token", "delta": delta}
            except Exception as exc:
                logger.warning("stream turn failed: %s", exc)
                error = _describe_exc(exc)
            finally:
                # A per-chunk timeout cancels the in-flight ``__anext__`` task;
                # closing a generator in that state can itself raise. Swallow it
                # so cleanup never masks the turn's real error.
                aclose = getattr(stream_gen, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception as close_exc:  # noqa: BLE001
                        logger.warning("stream aclose failed: %s", close_exc)
            yield {
                "_turn": True,
                "content": content,
                "tool_calls": tool_calls,
                "finish_reason": finish_reason,
                "tokens": prompt_tokens + completion_tokens,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": (time.monotonic() - llm_t0) * 1000.0,
                "model": model,
                "reasoning_content": None,
                "error": error,
            }
            return

        try:
            response = await asyncio.wait_for(
                self._llm_gateway.chat(
                    messages=messages,
                    tools=tool_descriptors,
                    cache_key_parts={
                        "call_type": "chat",
                        "prompt_version": config.name,
                    },
                ),
                timeout=llm_timeout,
            )
        except Exception as exc:
            logger.warning("chat turn failed: %s", exc)
            yield {
                "_turn": True,
                "content": "",
                "tool_calls": None,
                "finish_reason": "",
                "tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency_ms": (time.monotonic() - llm_t0) * 1000.0,
                "model": "",
                "reasoning_content": None,
                "error": _describe_exc(exc),
            }
            return
        usage = response.metadata.get("usage", {})
        yield {
            "_turn": True,
            "content": response.content or "",
            "tool_calls": response.metadata.get("tool_calls"),
            "finish_reason": str(response.metadata.get("finish_reason", "") or ""),
            "tokens": int(usage.get("total_tokens", 0) or 0),
            "prompt_tokens": int(
                usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
            ),
            "completion_tokens": int(
                usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
            ),
            "latency_ms": (time.monotonic() - llm_t0) * 1000.0,
            "model": str(response.metadata.get("model", "")),
            "reasoning_content": response.metadata.get("reasoning_content"),
            "error": None,
        }

    async def _execute_approved_calls(
        self,
        approved_calls: list[dict[str, Any]],
        *,
        config: Any,
        chain_id: str,
        tool_deps: ToolDeps | None,
        messages: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
        agent_mode: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute human-confirmed tool calls before the agent loop runs.

        Each approved call is seeded into ``messages`` as a completed assistant
        tool_call + tool result so the next LLM turn can summarise it. The
        confirm permission is bypassed (that *is* the approval), but ``deny``
        and analyze-mode denial still hard-block — a forged approval can never
        run a denied or read-only-mode-blocked tool. Yields a ``step`` event per
        executed call for streaming callers.
        """
        pipeline_perms: dict[str, str] = getattr(config, "tool_permissions", {}) or {}
        for call in approved_calls:
            tc_name = str(call.get("tool") or "")
            tc_args = dict(call.get("args") or {})
            tc_id = f"confirmed-{uuid.uuid4()}"

            tool_raw = self._tool_registry.get(tc_name)
            if tool_raw is None:
                tool_results.append(
                    {"tool": tc_name, "output": None, "error": "unknown_tool"}
                )
                continue

            override = pipeline_perms.get(tc_name)
            if override is not None:
                effective_perm = PermissionLevel(override)
            elif isinstance(tool_raw, ToolDefinition):
                effective_perm = tool_raw.permission_level
            else:
                effective_perm = PermissionLevel.auto
            blocked = (
                "denied_by_permission"
                if effective_perm is PermissionLevel.deny
                else (
                    "denied_by_analyze_mode"
                    if self._tool_perms.is_analyze_denied(tc_name, agent_mode)
                    else None
                )
            )
            if blocked is not None:
                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps({"status": blocked, "tool": tc_name}),
                        "tool_call_id": tc_id,
                    }
                )
                tool_results.append(
                    {"tool": tc_name, "status": blocked, "output": None}
                )
                continue

            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": tc_id,
                            "type": "function",
                            "function": {
                                "name": tc_name,
                                "arguments": json.dumps(tc_args, default=str),
                            },
                        }
                    ],
                }
            )
            exec_args = (
                {**tc_args, "tool_deps": tool_deps}
                if tool_deps is not None
                else tc_args
            )
            tool_fn = _resolve_callable(tool_raw)
            tool_t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    tool_fn(**exec_args),
                    timeout=_normalize_timeout(
                        getattr(config, "tool_timeout_s", _DEFAULT_TOOL_TIMEOUT_S)
                    ),
                )
                duration_ms = (time.monotonic() - tool_t0) * 1000.0
                await self._observer.tool_call(
                    config.name, chain_id, tc_name, duration_ms, "success"
                )
                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(result, default=str),
                        "tool_call_id": tc_id,
                    }
                )
                tool_results.append(
                    {"tool": tc_name, "output": result, "confirmed": True}
                )
                yield {
                    "type": "step",
                    "step": 0,
                    "action": "tool_call",
                    "tool": tc_name,
                    "duration_ms": duration_ms,
                    "status": "success",
                }
            except Exception as exc:
                duration_ms = (time.monotonic() - tool_t0) * 1000.0
                logger.warning("Confirmed tool %s failed: %s", tc_name, exc)
                await self._observer.tool_call(
                    config.name, chain_id, tc_name, duration_ms, "error", error=str(exc)
                )
                messages.append(
                    {
                        "role": "tool",
                        "content": _tool_error_payload(tc_name, exc),
                        "tool_call_id": tc_id,
                    }
                )
                tool_results.append(
                    {
                        "tool": tc_name,
                        "output": None,
                        "error": _describe_exc(exc),
                        "confirmed": True,
                    }
                )
                yield {
                    "type": "step",
                    "step": 0,
                    "action": "tool_call",
                    "tool": tc_name,
                    "duration_ms": duration_ms,
                    "status": "error",
                    "error": str(exc),
                }


_MAX_TOOL_ERROR_CHARS = 200


def _validate_history(messages: list[dict[str, Any]]) -> list[str]:
    """Return tool-call protocol violations in a message list (empty == valid).

    Every assistant ``tool_calls`` entry must be answered by a ``tool`` message
    with the matching ``tool_call_id`` before the next assistant/user turn, and
    every ``tool`` message must answer a still-open tool_call. Serves as a
    pre-send soft check and as the invariant the context compressor preserves.
    """
    problems: list[str] = []
    open_ids: set[str] = set()
    for idx, message in enumerate(messages):
        role = message.get("role")
        if role == "tool":
            tid = str(message.get("tool_call_id", ""))
            if tid in open_ids:
                open_ids.discard(tid)
            else:
                problems.append(f"tool message #{idx} answers no open tool_call")
            continue
        if open_ids:
            problems.append(f"unanswered tool_calls before #{idx}: {sorted(open_ids)}")
            open_ids.clear()
        if role == "assistant":
            for tool_call in message.get("tool_calls") or []:
                tid = str(tool_call.get("id", ""))
                if tid:
                    open_ids.add(tid)
    if open_ids:
        problems.append(f"unanswered tool_calls at end: {sorted(open_ids)}")
    return problems


def _normalize_timeout(value: Any) -> float | None:
    """Positive numeric timeout for ``asyncio.wait_for``; else no deadline.

    ``config`` is duck-typed (PipelineConfig / ORM row / mock), so a missing or
    non-numeric attribute must degrade to "no deadline" rather than raise.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


def _describe_exc(exc: BaseException) -> str:
    """Truncated description of an exception; falls back to the type name.

    ``str(TimeoutError())`` is empty, so a bare deadline would otherwise
    surface as an empty error string — the type name keeps it meaningful.
    """
    return (str(exc) or type(exc).__name__)[:_MAX_TOOL_ERROR_CHARS]


def _tool_error_payload(tool_name: str, exc: BaseException) -> str:
    """JSON tool-message body for a failed tool call (structured, truncated).

    Matches the deny/preview branches' JSON shape so the model parses every
    tool outcome uniformly, and caps the raw exception text so a long message
    carrying connection strings / internal paths is not replayed verbatim.
    """
    return json.dumps(
        {
            "status": "error",
            "tool": tool_name,
            "error": _describe_exc(exc),
        }
    )


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


def _extract_search_sources(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull source-like rows out of a search tool result dict.

    Mirrors the shape used by ``api.routers.search._search_step_items``
    (response.items or top-level contents/items) and projects each row to
    {title, url, content_id}. Returns [] when no recognisable rows exist.
    """
    raw: list[Any] = []
    response = result.get("response")
    if isinstance(response, dict):
        items = response.get("items")
        if isinstance(items, list):
            raw = items
    if not raw:
        for key in ("contents", "items"):
            candidate = result.get(key)
            if isinstance(candidate, list):
                raw = candidate
                break

    sources: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        sources.append(
            {
                "title": str(item.get("title", "")),
                "url": item.get("url"),
                "content_id": item.get("content_id") or item.get("id"),
            }
        )
    return sources


def _session_messages(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Return prior conversation turns from a session payload.

    Only plain user/assistant text turns survive rehydration. A tool round-trip
    (an assistant carrying ``tool_calls`` plus its ``tool`` results) is ephemeral
    to the run that produced it and cannot be re-paired across a session
    boundary, so keeping a bare ``tool`` message — or an assistant whose
    ``tool_calls`` have no following responses — would orphan the provider's
    tool-call protocol. Such messages are dropped rather than passed through.
    """
    raw_messages = session.get("messages")
    if not isinstance(raw_messages, list):
        return []
    messages: list[dict[str, Any]] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        if item.get("tool_calls"):
            continue
        messages.append({"role": role, "content": content})
    return messages
