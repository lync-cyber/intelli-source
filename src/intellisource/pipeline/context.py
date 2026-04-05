"""PipelineContext: key-value storage for passing data between processors."""

from typing import Any


class PipelineContext:
    """Key-value storage for passing data between processors."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """Set a key-value pair in the context."""
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value by key, returning default if not found."""
        return self._data.get(key, default)
