"""Subscription CRUD tool execute functions + descriptors."""

from __future__ import annotations

from typing import Any

from intellisource.agent.tools._spec import ToolDefinition
from intellisource.agent.tools.executes._crud import (
    _crud,
    _parse_uuid,
    _ToolInputError,
    _validated,
)
from intellisource.agent.tools.executes.manage._shared import _pick
from intellisource.agent.tools.results import tool_error, tool_ok
from intellisource.config.subscription_models import SubscriptionConfig

_SUB_FIELDS = (
    "name",
    "channel",
    "channel_config",
    "match_rules",
    "frequency",
    "quiet_hours",
    "timezone",
    "discipline_tags",
)
# Patch field set routes straight to ``Service.patch`` → ``repo.update`` (any
# column), so it may include ``status`` which the create-side SubscriptionConfig
# does not accept.
_SUB_PATCH_FIELDS = (*_SUB_FIELDS, "status")


def _serialize_subscription(s: Any) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "channel": s.channel,
        "status": s.status,
        "frequency": getattr(s, "frequency", None),
        "match_rules": dict(getattr(s, "match_rules", None) or {}),
    }


@_crud("create_subscription", "subscription_service_factory")
async def _create_subscription_execute(
    factory: Any, session_factory: Any, **kwargs: Any
) -> dict[str, Any]:
    """Create a subscription from LLM-supplied fields."""
    cfg = _validated(lambda: SubscriptionConfig(**_pick(kwargs, _SUB_FIELDS)))
    async with session_factory() as session:
        created = await factory(session).create(cfg)
        payload = {
            "id": str(created.id),
            "name": created.name,
            "channel": created.channel,
            "status": created.status,
        }
        await session.commit()
    return tool_ok("create_subscription", subscription=payload)


@_crud("list_subscriptions", "subscription_service_factory")
async def _list_subscriptions_execute(
    factory: Any, session_factory: Any, limit: int = 20, **kwargs: Any
) -> dict[str, Any]:
    """List subscriptions (id / name / channel / status)."""
    limit = int(limit)
    async with session_factory() as session:
        result = await factory(session).list_paginated(limit=min(limit, 100))
        items = [
            {
                "id": str(s.id),
                "name": s.name,
                "channel": s.channel,
                "status": s.status,
            }
            for s in result["items"]
        ]
    return tool_ok("list_subscriptions", items=items, count=len(items))


@_crud("get_subscription", "subscription_service_factory")
async def _get_subscription_execute(
    factory: Any, session_factory: Any, subscription_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Fetch a single subscription by id."""
    sid = _parse_uuid(subscription_id, "subscription_id")
    async with session_factory() as session:
        row = await factory(session).get(sid)
    if row is None:
        return tool_error(
            "get_subscription", "subscription not found", code="not_found"
        )
    return tool_ok("get_subscription", subscription=_serialize_subscription(row))


@_crud("update_subscription", "subscription_service_factory")
async def _update_subscription_execute(
    factory: Any, session_factory: Any, subscription_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Partial-update an existing subscription by id (real patch)."""
    sid = _parse_uuid(subscription_id, "subscription_id")
    fields = _pick(kwargs, _SUB_PATCH_FIELDS)
    if not fields:
        raise _ToolInputError("no fields to update")
    async with session_factory() as session:
        updated = await factory(session).patch(sid, fields)
        if updated is None:
            return tool_error(
                "update_subscription", "subscription not found", code="not_found"
            )
        payload = _serialize_subscription(updated)
        await session.commit()
    return tool_ok("update_subscription", subscription=payload)


@_crud("delete_subscription", "subscription_service_factory")
async def _delete_subscription_execute(
    factory: Any, session_factory: Any, subscription_id: str = "", **kwargs: Any
) -> dict[str, Any]:
    """Soft-delete a subscription by id (status='paused')."""
    sid = _parse_uuid(subscription_id, "subscription_id")
    async with session_factory() as session:
        deleted = await factory(session).delete(sid)
        await session.commit()
    if not deleted:
        return tool_error(
            "delete_subscription", "subscription not found", code="not_found"
        )
    return tool_ok("delete_subscription", subscription_id=str(sid))


SUBSCRIPTION_TOOL_DEFS: list[ToolDefinition] = [
    ToolDefinition(
        name="create_subscription",
        description="Create a subscription on a channel (email/wechat/wework).",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "channel": {
                    "type": "string",
                    "enum": ["email", "wechat", "wework"],
                },
                "channel_config": {"type": "object"},
                "match_rules": {"type": "object"},
                "frequency": {"type": "string"},
            },
            "required": ["name", "channel"],
        },
        execute=_create_subscription_execute,
        mutates_external_state=True,
    ),
    ToolDefinition(
        name="list_subscriptions",
        description="List configured subscriptions.",
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
        execute=_list_subscriptions_execute,
    ),
    ToolDefinition(
        name="get_subscription",
        description=(
            "Fetch a single subscription by id, returning its channel,"
            " status, frequency and match rules."
        ),
        parameters={
            "type": "object",
            "properties": {
                "subscription_id": {
                    "type": "string",
                    "description": "UUID of the subscription to fetch.",
                }
            },
            "required": ["subscription_id"],
        },
        execute=_get_subscription_execute,
    ),
    ToolDefinition(
        name="update_subscription",
        description=(
            "Partially update an EXISTING subscription by id. Only supplied"
            " fields change; the subscription must already exist (use"
            " create_subscription to add a new one). Call get_subscription /"
            " list_subscriptions first to confirm the id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "subscription_id": {
                    "type": "string",
                    "description": "UUID of the subscription to update.",
                },
                "name": {"type": "string"},
                "channel_config": {"type": "object"},
                "match_rules": {"type": "object"},
                "frequency": {"type": "string"},
                "quiet_hours": {"type": "object"},
                "timezone": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["active", "paused"],
                },
            },
            "required": ["subscription_id"],
        },
        execute=_update_subscription_execute,
        mutates_external_state=True,
    ),
    ToolDefinition(
        name="delete_subscription",
        description="Soft-delete (pause) a subscription by id.",
        parameters={
            "type": "object",
            "properties": {"subscription_id": {"type": "string"}},
            "required": ["subscription_id"],
        },
        execute=_delete_subscription_execute,
        mutates_external_state=True,
    ),
]
