"""Static chat web UI — a minimal HTML+SSE frontend over /search/chat/stream."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from intellisource.core.encoding import read_text

router = APIRouter(tags=["web"])

_CHAT_HTML = Path(__file__).resolve().parent.parent / "static" / "chat.html"


@router.get("/chat", response_class=HTMLResponse, include_in_schema=False)
async def chat_page() -> HTMLResponse:
    """Serve the chat page; its JS streams /api/v1/search/chat/stream via fetch SSE."""
    return HTMLResponse(read_text(_CHAT_HTML))
