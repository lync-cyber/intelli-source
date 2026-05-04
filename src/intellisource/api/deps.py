"""FastAPI dependency injection helpers.

Provides reusable dependencies for request-scoped resources
such as database sessions and API key validation.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from fastapi import Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session from app.state.db for the request scope."""
    async with request.app.state.db.get_session() as session:
        yield session


def require_api_key(
    x_api_key: str = Header("", alias="x-api-key"),
) -> str:
    """Validate the X-API-Key header against IS_API_KEY env var.

    Raises:
        HTTPException: 401 if key is missing or invalid.

    Returns:
        The validated API key string.
    """
    expected = os.environ.get("IS_API_KEY", "")
    if not expected:
        return x_api_key
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key
