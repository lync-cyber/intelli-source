"""Distribution control-plane router: channels / templates / push records + trigger.

Read endpoints expose the distribution catalog (which channels and digest
templates exist) and the push-record audit trail; the trigger dispatches an
on-demand digest assembly, complementing the periodic beat schedule.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.api.schemas.distribution import (
    AssembleTriggerResponse,
    ChannelInfo,
    ChannelListResponse,
    PushRecordListResponse,
    TemplateInfo,
    TemplateListResponse,
)
from intellisource.distributor.channels.registry import (
    channel_is_configured,
    list_channel_descriptors,
)
from intellisource.distributor.templates import TEMPLATE_REGISTRY
from intellisource.scheduler.dispatch import send_task_with_trace
from intellisource.storage.repositories.push import PushRepository

router = APIRouter(tags=["distribution"])


def _mask_recipient(recipient: str | None) -> str | None:
    """Redact a push recipient so the audit trail does not leak PII.

    ``alice@example.com`` -> ``a***@example.com``; an opaque id -> ``a***``.
    """
    if not recipient:
        return recipient
    if "@" in recipient:
        local, _, domain = recipient.partition("@")
        head = local[0] if local else ""
        return f"{head}***@{domain}"
    return f"{recipient[0]}***"


def _serialize_push_record(record: Any) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "subscription_id": (
            str(record.subscription_id) if record.subscription_id else None
        ),
        "content_id": str(record.content_id) if record.content_id else None,
        "channel": record.channel,
        "status": record.status,
        "retry_count": record.retry_count,
        "error_message": record.error_message,
        "recipient": _mask_recipient(record.recipient_id),
        "sent_at": record.sent_at,
        "delivered_at": record.delivered_at,
        "created_at": record.created_at,
    }


@router.get("/channels", response_model=ChannelListResponse)
async def list_channels() -> dict[str, Any]:
    """List every distribution channel and whether its credentials are present."""
    items = [
        ChannelInfo(
            name=desc.name,
            display_name=desc.display_name,
            required_env=list(desc.required_env),
            configured=channel_is_configured(desc, os.environ),
        )
        for desc in list_channel_descriptors()
    ]
    return {"items": items}


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates() -> dict[str, Any]:
    """List every registered digest template and the formats it renders."""
    items = [
        TemplateInfo(
            name=template.name,
            formats=sorted(template.formats),
            default_format=template.default_format,
        )
        for template in TEMPLATE_REGISTRY.values()
    ]
    return {"items": items}


@router.get("/push-records", response_model=PushRecordListResponse)
async def list_push_records(
    limit: int = 20,
    cursor: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return the cursor-paginated push-record audit trail (PII-masked)."""
    limit = min(limit, 100)
    repo = PushRepository(session)
    result = await repo.list(limit=limit, cursor=cursor)
    return {
        "items": [_serialize_push_record(r) for r in result["items"]],
        "next_cursor": result["next_cursor"],
        "has_more": result["has_more"],
    }


@router.post("/distributions/assemble", response_model=AssembleTriggerResponse)
async def trigger_digest_assembly(request: Request) -> dict[str, Any]:
    """Dispatch an on-demand daily/weekly digest assembly (beat-independent)."""
    celery_instance = getattr(request.app.state, "celery_app", None)
    if celery_instance is None:
        raise HTTPException(status_code=503, detail="celery_app not initialised")
    result = send_task_with_trace(
        "assemble_daily_weekly_digests",
        celery_instance=celery_instance,
    )
    return {"task_id": str(getattr(result, "id", result))}
