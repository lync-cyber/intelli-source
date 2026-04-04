"""Error classification framework for IntelliSource.

Defines a categorized exception hierarchy with recovery strategies,
matching the architecture specification (arch section 5.3).
"""

from __future__ import annotations

from enum import Enum


class ErrorCategory(Enum):
    """Error categories with associated recovery strategies."""

    RECOVERABLE_TRANSIENT = "RECOVERABLE_TRANSIENT"
    RECOVERABLE_DEGRADED = "RECOVERABLE_DEGRADED"
    UNRECOVERABLE = "UNRECOVERABLE"
    EXTERNAL = "EXTERNAL"

    @property
    def recovery_strategy(self) -> str:
        """Return the recovery strategy description for this category."""
        return _RECOVERY_STRATEGIES[self]


_RECOVERY_STRATEGIES: dict[ErrorCategory, str] = {
    ErrorCategory.RECOVERABLE_TRANSIENT: "自动重试（指数退避）",
    ErrorCategory.RECOVERABLE_DEGRADED: "降级到传统逻辑",
    ErrorCategory.UNRECOVERABLE: "记录错误 + 告警，跳过当前项",
    ErrorCategory.EXTERNAL: "触发熔断，批量跳过",
}


class IntelliSourceError(Exception):
    """Base exception for all IntelliSource errors."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory,
        recovery_hint: str = "",
    ) -> None:
        super().__init__(message)
        self.category = category
        self.recovery_hint = recovery_hint


class CollectorError(IntelliSourceError):
    """Error raised by the collector module."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.RECOVERABLE_TRANSIENT,
        recovery_hint: str = "",
    ) -> None:
        super().__init__(message, category=category, recovery_hint=recovery_hint)


class PipelineError(IntelliSourceError):
    """Error raised by the pipeline module."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.UNRECOVERABLE,
        recovery_hint: str = "",
    ) -> None:
        super().__init__(message, category=category, recovery_hint=recovery_hint)


class LLMError(IntelliSourceError):
    """Error raised by the LLM module."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.RECOVERABLE_DEGRADED,
        recovery_hint: str = "",
    ) -> None:
        super().__init__(message, category=category, recovery_hint=recovery_hint)


class DistributorError(IntelliSourceError):
    """Error raised by the distributor module."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.RECOVERABLE_TRANSIENT,
        recovery_hint: str = "",
    ) -> None:
        super().__init__(message, category=category, recovery_hint=recovery_hint)


class StorageError(IntelliSourceError):
    """Error raised by the storage module."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.UNRECOVERABLE,
        recovery_hint: str = "",
    ) -> None:
        super().__init__(message, category=category, recovery_hint=recovery_hint)
