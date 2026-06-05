"""Collect tool execute function."""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from intellisource.agent.deps import ToolDeps
from intellisource.agent.tools.results import tool_degraded
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


async def _collect_execute(
    source_id: str = "",
    source_type: str = "",
    tool_deps: ToolDeps | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Collect from source, persist RawContent rows, return ids for downstream steps."""
    if tool_deps is None or tool_deps.collector_registry is None:
        logger.warning("tool_deps not injected for collect, returning placeholder")
        return tool_degraded(
            "collect",
            "tool_deps not injected",
            collected=[],
            source_id=source_id,
        )

    source_config: dict[str, Any] = {}
    source_uuid: _uuid.UUID | None = None
    task_id_raw = kwargs.get("task_id") or kwargs.get("collect_task_id")
    collect_task_id: _uuid.UUID | None = None
    if task_id_raw:
        try:
            collect_task_id = _uuid.UUID(str(task_id_raw))
        except ValueError:
            collect_task_id = None

    if tool_deps.session_factory is not None and source_id:
        try:
            from intellisource.storage.repositories.source import (  # noqa: PLC0415
                SourceRepository,
            )

            source_uuid = _uuid.UUID(source_id)
            async with tool_deps.session_factory() as session:
                source_row = await SourceRepository(session).get_by_id(source_uuid)
            if source_row is not None:
                if not source_type:
                    source_type = str(source_row.type or "")
                source_config = {
                    "url": source_row.url,
                    "source_id": source_id,
                    "source_type": source_type,
                    "proxy": source_row.proxy,
                    "rate_limit_qps": source_row.rate_limit_qps,
                    "rate_limit_concurrency": source_row.rate_limit_concurrency,
                    "metadata": source_row.metadata_,
                }
        except Exception as exc:
            logger.warning(
                "_collect_execute: failed to load Source for %s: %s",
                source_id,
                exc,
            )

    if not source_config:
        source_config = {
            "url": source_id,
            "source_id": source_id,
            "source_type": source_type,
        }
        if source_id:
            try:
                source_uuid = _uuid.UUID(source_id)
            except ValueError:
                source_uuid = None

    from intellisource.collector.base import RawContent as CollectedRawContent
    from intellisource.core.errors import CollectorError  # noqa: PLC0415

    try:
        collector = tool_deps.collector_registry.get(source_type)
    except CollectorError:
        return tool_degraded(
            "collect",
            f"unknown source_type: {source_type}",
            collected=[],
            source_id=source_id,
        )

    collected_items: list[CollectedRawContent] = await collector.collect(
        source_config=source_config
    )

    raw_content_ids: list[str] = []
    collected_summary: list[dict[str, Any]] = []

    if tool_deps.session_factory is not None and source_uuid is not None:
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        async with tool_deps.session_factory() as session:
            repo = ContentRepository(session=session)
            for item in collected_items:
                existing = await repo.get_raw_by_fingerprint(item.fingerprint)
                if existing is not None:
                    raw_content_ids.append(str(existing.id))
                    collected_summary.append(
                        {
                            "id": str(existing.id),
                            "title": existing.title,
                            "source_url": existing.source_url,
                            "duplicate": True,
                        }
                    )
                    continue
                raw = await repo.create_raw(
                    source_id=source_uuid,
                    source_url=item.source_url,
                    fingerprint=item.fingerprint,
                    title=item.title,
                    author=item.author,
                    body_html=item.body_html,
                    body_text=item.body_text,
                    published_at=item.published_at,
                    raw_metadata=dict(item.raw_metadata),
                    collect_task_id=collect_task_id,
                )
                raw_content_ids.append(str(raw.id))
                collected_summary.append(
                    {
                        "id": str(raw.id),
                        "title": raw.title,
                        "source_url": raw.source_url,
                        "duplicate": False,
                    }
                )
            await session.commit()
    else:
        for item in collected_items:
            collected_summary.append(
                {
                    "title": item.title,
                    "source_url": item.source_url,
                    "fingerprint": item.fingerprint,
                }
            )

    first_id = raw_content_ids[0] if raw_content_ids else None
    return {
        "status": "ok",
        "tool": "collect",
        "collected": collected_summary,
        "raw_content_ids": raw_content_ids,
        "content_id": first_id,
        "is_batch": True,
        "source_id": source_id,
        "source_type": source_type,
    }
