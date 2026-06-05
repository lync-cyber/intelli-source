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


class CompositionError(IntelliSourceError, ValueError):
    """Raised when the composition root receives invalid dependencies.

    Multiple inheritance keeps `isinstance(exc, ValueError)` true so callers
    that catch the built-in `ValueError` (and existing tests) still match.
    """

    def __init__(self, message: str) -> None:
        IntelliSourceError.__init__(
            self,
            message,
            category=ErrorCategory.UNRECOVERABLE,
            recovery_hint=(
                "Wire dependencies via build_worker_composition() or "
                "build_api_composition()"
            ),
        )


class CompositionNotInitialisedError(IntelliSourceError, RuntimeError):
    """Raised when a process-wide singleton is read before composition root ran.

    Multiple inheritance preserves `isinstance(exc, RuntimeError)` for callers
    catching the built-in.
    """

    def __init__(self, message: str) -> None:
        IntelliSourceError.__init__(
            self,
            message,
            category=ErrorCategory.UNRECOVERABLE,
            recovery_hint=(
                "Call build_worker_composition() (Worker) or "
                "build_api_composition() (API) before reaching this code path"
            ),
        )
