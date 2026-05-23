"""Pydantic schemas for /search/chat endpoint (AC-2)."""

from __future__ import annotations

from pydantic import BaseModel


class ChatSource(BaseModel):
    """A source reference returned in the chat response."""

    title: str
    url: str | None = None
    content_id: str | None = None


class ChatSearchRequest(BaseModel):
    """Request body for POST /search/chat."""

    message: str
    session_id: str | None = None
    session: dict[str, object] | None = None
    max_tokens_budget: int | None = None


class ChatSearchResponse(BaseModel):
    """Response body for POST /search/chat."""

    session_id: str
    answer: str
    sources: list[ChatSource]
    steps_executed: int
    task_chain_id: str
