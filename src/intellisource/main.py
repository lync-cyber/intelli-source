"""FastAPI application entry point for IntelliSource."""

from fastapi import FastAPI

_DESCRIPTION = (
    "AI-powered intelligent information aggregation and distribution platform"
)

app: FastAPI = FastAPI(
    title="IntelliSource",
    description=_DESCRIPTION,
    version="0.1.0",
)
