"""Process tool execute function."""

from __future__ import annotations

import asyncio
import logging
import uuid as _uuid
from typing import Any

logger = logging.getLogger(__name__)


async def _process_execute(
    content_id: str = "",
    raw_content_ids: list[str] | None = None,
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Fetch RawContent, run PipelineEngine, persist ProcessedContent.

    When ``raw_content_ids`` is provided the function fans-out over the full
    list; ``content_id`` is used as a single-item fallback for backward
    compatibility.
    """
    if tool_deps is None or tool_deps.pipeline_engine is None:
        logger.warning("tool_deps not injected for process, returning placeholder")
        return {
            "status": "degraded",
            "tool": "process",
            "reason": "tool_deps not injected",
            "content_id": content_id,
        }

    if tool_deps.session_factory is None:
        logger.warning(
            "session_factory not injected for process, returning placeholder"
        )
        return {
            "status": "degraded",
            "tool": "process",
            "reason": "session_factory not injected",
            "content_id": content_id,
        }

    ids_to_process: list[str] = (
        raw_content_ids if raw_content_ids else ([content_id] if content_id else [])
    )

    if not ids_to_process:
        return {
            "status": "degraded",
            "tool": "process",
            "reason": "no content_id provided",
            "content_id": content_id,
        }

    from datetime import datetime, timezone  # noqa: PLC0415

    from intellisource.pipeline.context import PipelineContext  # noqa: PLC0415
    from intellisource.storage.repositories.content import (  # noqa: PLC0415
        ContentRepository,
    )

    processed_content_ids: list[str] = []
    results: list[dict[str, Any]] = []

    for cid in ids_to_process:
        try:
            raw_id = _uuid.UUID(cid)
        except ValueError:
            results.append(
                {
                    "status": "degraded",
                    "reason": f"invalid content_id: {cid!r}",
                    "content_id": cid,
                }
            )
            continue

        ctx = PipelineContext()
        ctx.set("content_id", cid)

        async with tool_deps.session_factory() as session:
            repo = ContentRepository(session=session)
            raw = await repo.get_raw_by_id(raw_id)
            if raw is None:
                results.append(
                    {
                        "status": "degraded",
                        "reason": f"RawContent not found: {cid}",
                        "content_id": cid,
                    }
                )
                continue

            ctx.set("body_html", raw.body_html or "")
            ctx.set("body_text", raw.body_text or "")
            ctx.set("title", raw.title or "")
            ctx.set("fingerprint", raw.fingerprint or "")
            ctx.set("content_id", str(raw.id))

            ctx = await asyncio.to_thread(tool_deps.pipeline_engine.execute, ctx)

            tags_val = ctx.get("tags")
            tags: list[str] = tags_val if isinstance(tags_val, list) else []

            existing_processed = await repo.get_processed_by_raw_id(raw_id)
            if existing_processed is not None:
                processed = existing_processed
            else:
                embedding_val = ctx.get("embedding")
                embedding_arg: list[float] | None = (
                    embedding_val if isinstance(embedding_val, list) else None
                )
                processed = await repo.create(
                    raw_content_id=raw_id,
                    title=str(ctx.get("title") or raw.title or ""),
                    body_text=str(ctx.get("body_text") or raw.body_text or ""),
                    summary=str(ctx.get("summary") or ""),
                    tags=tags,
                    embedding=embedding_arg,
                    fingerprint=str(ctx.get("fingerprint") or raw.fingerprint or ""),
                    source_url=raw.source_url,
                    processing_status="completed",
                    processed_at=datetime.now(tz=timezone.utc),
                )

            raw.status = "processed"
            raw.processed_at = datetime.now(tz=timezone.utc)
            await session.commit()

        processed_id = str(processed.id)
        processed_content_ids.append(processed_id)
        results.append(
            {
                "body_html": ctx.get("body_html"),
                "body_text": ctx.get("body_text"),
                "title": ctx.get("title"),
                "fingerprint": ctx.get("fingerprint"),
                "content_id": processed_id,
                "raw_content_id": str(raw_id),
            }
        )

    first_processed_id = (
        processed_content_ids[0] if processed_content_ids else content_id
    )
    single_result = results[0] if len(results) == 1 else results
    return {
        "status": "ok",
        "tool": "process",
        "result": single_result,
        "processed_content_ids": processed_content_ids,
        "content_id": first_processed_id,
    }
