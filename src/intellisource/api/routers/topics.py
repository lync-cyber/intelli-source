"""Topics API router — HTTP shell over TopicService (built-in topic catalog)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.api.schemas.common import OperationResult
from intellisource.api.schemas.topics import TopicDetail, TopicListResponse
from intellisource.config.subscription_models import ChannelType
from intellisource.config.subscription_validator import SubscriptionValidationError
from intellisource.config.validator import ConfigValidationError
from intellisource.topic.models import Topic
from intellisource.topic.service import TopicNotFoundError, TopicService

router = APIRouter(tags=["topics"])


class TopicEnableRequest(BaseModel):
    """Enable body: optional channel provisions the topic's default subscription."""

    channel: ChannelType | None = None
    channel_config: dict[str, Any] = {}
    create_subscription: bool = True
    subscription_name: str | None = None


def _get_service(
    session: AsyncSession = Depends(get_db_session),
) -> TopicService:
    return TopicService(session)


def _serialize_topic(topic: Topic, *, detail: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": topic.id,
        "name": topic.name,
        "dimension": topic.dimension,
        "description": topic.description,
        "tags": topic.tags,
        "discipline_tags": topic.discipline_tags,
        "source_count": len(topic.sources),
    }
    if detail:
        data["sources"] = [
            {
                "name": s.name,
                "type": s.type,
                "url": s.url,
                "tags": s.tags,
                "discipline_tags": s.discipline_tags,
            }
            for s in topic.sources
        ]
        tmpl = topic.subscription_template
        data["subscription_template"] = (
            None
            if tmpl is None
            else {
                "name": tmpl.name,
                "frequency": tmpl.frequency,
                "match_rules": tmpl.match_rules,
                "discipline_tags": tmpl.discipline_tags,
            }
        )
    return data


@router.get("/topics", response_model=TopicListResponse)
def list_topics(
    service: TopicService = Depends(_get_service),
) -> dict[str, Any]:
    return {"items": [_serialize_topic(t) for t in service.list_topics()]}


@router.get("/topics/{topic_id}", response_model=TopicDetail)
def get_topic(
    topic_id: str,
    service: TopicService = Depends(_get_service),
) -> Any:
    topic = service.get_topic(topic_id)
    if topic is None:
        return JSONResponse(status_code=404, content={"detail": "topic not found"})
    return _serialize_topic(topic, detail=True)


@router.post("/topics/{topic_id}/enable", response_model=OperationResult)
async def enable_topic(
    topic_id: str,
    body: TopicEnableRequest,
    service: TopicService = Depends(_get_service),
) -> Any:
    """Sync the topic's sources (additive + snapshot) and optionally subscribe."""
    try:
        return await service.enable(
            topic_id,
            channel=body.channel,
            channel_config=body.channel_config,
            create_subscription=body.create_subscription,
            subscription_name=body.subscription_name,
        )
    except TopicNotFoundError:
        return JSONResponse(status_code=404, content={"detail": "topic not found"})
    except (ConfigValidationError, SubscriptionValidationError) as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
