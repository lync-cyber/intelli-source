"""Shared response-schema primitives.

``APIModel`` is the base for every response model. ``extra="allow"`` means a
handler dict carrying fields the model does not declare is passed through
unchanged rather than silently dropped — so adding response_model to an existing
endpoint is contract-documenting without changing the emitted payload. Models
therefore declare only fields that are *always* present in the success dict.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    """Response-model base that never drops handler-emitted fields."""

    model_config = ConfigDict(extra="allow")


class OperationResult(APIModel):
    """Permissive envelope for service-computed operational dicts.

    Used where the payload is an operation outcome (reload / diff / rollback /
    stats) whose exact keys are owned by the domain service rather than frozen
    at the transport layer.
    """
