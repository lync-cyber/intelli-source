"""BaseDistributor abstract base class."""

from __future__ import annotations

import abc
from typing import Any


class BaseDistributor(abc.ABC):
    """Abstract base class for content distributors."""

    @abc.abstractmethod
    async def distribute(self, content: Any, subscription: Any) -> Any:
        """Distribute content to a subscription."""
