"""Distribute tool execute function."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def _distribute_execute(
    content_id: str = "",
    processed_content_ids: list[str] | None = None,
    subscription_id: str = "",
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke distributor.distribute() for the given content and subscription.

    When ``processed_content_ids`` is provided the function fans-out over the
    full list; ``content_id`` is used as a single-item fallback for backward
    compatibility.
    """
    if tool_deps is None or tool_deps.distributor is None:
        logger.warning("tool_deps not injected for distribute, returning placeholder")
        return {
            "status": "degraded",
            "tool": "distribute",
            "reason": "tool_deps not injected",
            "content_id": content_id,
        }

    ids_to_distribute: list[str] = (
        processed_content_ids
        if processed_content_ids
        else ([content_id] if content_id else [])
    )

    if not ids_to_distribute:
        return {
            "status": "degraded",
            "tool": "distribute",
            "reason": "no content_id provided",
            "content_id": content_id,
        }

    results: list[Any] = []
    for cid in ids_to_distribute:
        r = await tool_deps.distributor.distribute(
            content_id=cid,
            subscription_id=subscription_id,
        )
        results.append(r)

    single_result = results[0] if len(results) == 1 else results
    return {"status": "ok", "tool": "distribute", "result": single_result}
