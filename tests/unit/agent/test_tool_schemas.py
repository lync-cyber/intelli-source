"""P0-3: built-in tool JSON schemas must match their real execute signatures.

The schemas are the only contract the LLM sees when deciding how to call a
tool. A schema that advertises a parameter the executor never accepts (e.g.
``channels``) or omits one the executor relies on (e.g. ``subscription_id``)
silently misleads the model — the latter was the root cause of the empty
``subscription_id`` distribution defect: the LLM was never told the parameter
existed, so it never supplied it.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from intellisource.agent.tools.executes.collect import _collect_execute
from intellisource.agent.tools.executes.distribute import _distribute_execute
from intellisource.agent.tools.executes.process import _process_execute
from intellisource.agent.tools.registry import AgentToolRegistry


def _props(name: str) -> dict[str, Any]:
    reg = AgentToolRegistry()
    reg.register_defaults()
    tool = reg.get(name)
    assert tool is not None, f"{name} not registered by register_defaults()"
    properties = tool.parameters.get("properties")
    assert isinstance(properties, dict)
    return properties


def _accepted_params(fn: Callable[..., Any]) -> set[str]:
    """Named keyword parameters the executor accepts (excludes tool_deps/**kwargs)."""
    return {
        p.name
        for p in inspect.signature(fn).parameters.values()
        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        and p.name not in {"tool_deps", "kwargs"}
    }


def test_distribute_schema_exposes_real_params() -> None:
    props = _props("distribute")
    assert "content_id" in props
    assert "processed_content_ids" in props
    # subscription_id is the parameter the executor actually routes on; it must
    # be advertised so the LLM can target a specific subscription.
    assert "subscription_id" in props
    # `channels` was never a parameter of _distribute_execute.
    assert "channels" not in props


def test_process_schema_exposes_real_params() -> None:
    props = _props("process")
    assert "content_id" in props
    assert "raw_content_ids" in props
    # `pipeline` was never a parameter of _process_execute.
    assert "pipeline" not in props


def test_collect_schema_documents_params() -> None:
    props = _props("collect")
    assert {"source_id", "source_type"} <= set(props)
    # every advertised property carries a description so the model understands it
    for name, schema in props.items():
        assert schema.get("description"), f"collect.{name} missing description"


def test_advertised_props_are_accepted_by_executor() -> None:
    """No tool may advertise a property its executor does not accept."""
    pairs: list[tuple[str, Callable[..., Any]]] = [
        ("distribute", _distribute_execute),
        ("process", _process_execute),
        ("collect", _collect_execute),
    ]
    for tool_name, fn in pairs:
        advertised = set(_props(tool_name))
        accepted = _accepted_params(fn)
        assert advertised <= accepted, (
            f"{tool_name} advertises {advertised - accepted} not accepted by"
            f" its executor (accepted={accepted})"
        )
