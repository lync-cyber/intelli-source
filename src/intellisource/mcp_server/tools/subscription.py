"""Subscription CRUD MCP tools."""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.mcp_server._serialize import only_set, subscription_dict
from intellisource.mcp_server._types import SessionFactory
from intellisource.subscription.service import SubscriptionService


def register_subscription_tools(mcp: FastMCP, session_cm: SessionFactory) -> None:
    @mcp.tool(
        name="list_subscriptions",
        description=(
            "List configured subscriptions. Params: limit (int, capped at 100)."
            " Returns a list of {id, name, channel, status}. Use the id with"
            " get_subscription / update_subscription / delete_subscription."
        ),
    )
    async def list_subscriptions(limit: int = 20) -> list[dict[str, Any]]:
        async with session_cm() as session:
            result = await SubscriptionService(session).list_paginated(
                limit=min(limit, 100)
            )
            return [subscription_dict(s) for s in result["items"]]

    @mcp.tool(
        name="get_subscription",
        description=(
            "Fetch one subscription by id. Params: subscription_id (UUID str)."
            " Returns the subscription (id, name, channel, status, frequency,"
            " match_rules) or {error:'not_found'} when absent."
        ),
    )
    async def get_subscription(subscription_id: str) -> dict[str, Any]:
        try:
            sid = _uuid.UUID(subscription_id)
        except ValueError:
            return {"error": "invalid_input", "reason": f"bad id: {subscription_id!r}"}
        async with session_cm() as session:
            row = await SubscriptionService(session).get(sid)
        if row is None:
            return {"error": "not_found", "subscription_id": subscription_id}
        return subscription_dict(row)

    @mcp.tool(
        name="create_subscription",
        description=(
            "Create a subscription on a channel. Params: name, channel"
            " (email/wechat/wework), channel_config (e.g. {to_addr} for email),"
            " match_rules, frequency. Returns {id, name, channel, status}, or"
            " {error:'invalid_input'} when channel rules are unmet (email needs"
            " a valid to_addr)."
        ),
    )
    async def create_subscription(
        name: str,
        channel: str,
        channel_config: dict[str, Any] | None = None,
        match_rules: dict[str, Any] | None = None,
        frequency: str = "realtime",
    ) -> dict[str, Any]:
        try:
            cfg = SubscriptionConfig.model_validate(
                {
                    "name": name,
                    "channel": channel,
                    "channel_config": channel_config or {},
                    "match_rules": match_rules or {},
                    "frequency": frequency,
                }
            )
        except Exception as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        try:
            async with session_cm() as session:
                created = await SubscriptionService(session).create(cfg)
                payload = {
                    "id": str(created.id),
                    "name": created.name,
                    "channel": created.channel,
                    "status": created.status,
                }
                await session.commit()
        except Exception as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        return payload

    @mcp.tool(
        name="update_subscription",
        description=(
            "Partially update an EXISTING subscription by id. Params:"
            " subscription_id (required) plus any of name, channel_config,"
            " match_rules, frequency, quiet_hours, timezone, status — only the"
            " ones you pass change. Returns the updated subscription, or"
            " {error:'not_found'} when the id is absent."
        ),
    )
    async def update_subscription(
        subscription_id: str,
        name: str | None = None,
        channel_config: dict[str, Any] | None = None,
        match_rules: dict[str, Any] | None = None,
        frequency: str | None = None,
        quiet_hours: dict[str, Any] | None = None,
        timezone: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        try:
            sid = _uuid.UUID(subscription_id)
        except ValueError:
            return {"error": "invalid_input", "reason": f"bad id: {subscription_id!r}"}
        fields = only_set(
            name=name,
            channel_config=channel_config,
            match_rules=match_rules,
            frequency=frequency,
            quiet_hours=quiet_hours,
            timezone=timezone,
            status=status,
        )
        if not fields:
            return {"error": "invalid_input", "reason": "no fields to update"}
        async with session_cm() as session:
            updated = await SubscriptionService(session).patch(sid, fields)
            if updated is None:
                return {"error": "not_found", "subscription_id": subscription_id}
            payload = subscription_dict(updated)
            await session.commit()
        return payload

    @mcp.tool(
        name="delete_subscription",
        description=(
            "Soft-delete (pause) a subscription by id. Params: subscription_id"
            " (UUID str). Returns {deleted: bool, subscription_id}. Soft delete"
            " preserves push-record history; deleted=false means the id was"
            " absent."
        ),
    )
    async def delete_subscription(subscription_id: str) -> dict[str, Any]:
        try:
            sid = _uuid.UUID(subscription_id)
        except ValueError:
            return {"error": "invalid_input", "reason": f"bad id: {subscription_id!r}"}
        async with session_cm() as session:
            deleted = await SubscriptionService(session).delete(sid)
            await session.commit()
        return {"deleted": deleted, "subscription_id": subscription_id}
