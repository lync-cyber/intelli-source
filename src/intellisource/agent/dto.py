"""Data transfer objects for agent tool return values."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ProcessedContentDTO(BaseModel):
    """Serializable representation of a ProcessedContent ORM row.

    Fields use ``Any`` so that MagicMock attributes in tests are accepted by
    pydantic without validation errors.  ``model_dump(mode="json")`` converts
    UUID / datetime / ORM objects to plain Python scalars via the custom
    ``model_dump`` override below.
    """

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    id: Any
    raw_content_id: Any = None
    title: Any = None
    body_text: Any = None
    summary: Any = None
    tags: Any = []
    fingerprint: Any = None
    source_url: Any = None
    created_at: Any = None

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Return a JSON-serializable dict with UUIDs converted to strings."""
        data = super().model_dump(**kwargs)

        def _coerce(v: Any) -> Any:
            if isinstance(v, uuid.UUID):
                return str(v)
            if isinstance(v, datetime):
                return v.isoformat()
            if isinstance(v, list):
                return [_coerce(x) for x in v]
            return v

        return {k: _coerce(v) for k, v in data.items()}
