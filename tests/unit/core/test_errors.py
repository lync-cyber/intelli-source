"""Tests for the error classification framework (T-007a).

Covers:
- AC-T007a-1: IntelliSourceError base class with category and recovery_hint
- AC-T007a-2: ErrorCategory enum values and recovery strategy descriptions
- AC-T007a-3: Module-specific exception classes with correct defaults
"""

import pytest

from intellisource.core.errors import (
    CollectorError,
    DistributorError,
    ErrorCategory,
    IntelliSourceError,
    LLMError,
    PipelineError,
    StorageError,
)

# ---------------------------------------------------------------------------
# AC-T007a-1: IntelliSourceError base class
# ---------------------------------------------------------------------------


class TestIntelliSourceErrorBase:
    """IntelliSourceError carries category (ErrorCategory) and recovery_hint (str)."""

    def test_is_exception_subclass(self):
        """IntelliSourceError should be a subclass of Exception."""
        assert issubclass(IntelliSourceError, Exception)

    def test_has_category_and_recovery_hint(self):
        """Instances expose category (ErrorCategory) and recovery_hint (str)."""
        err = IntelliSourceError(
            "something failed",
            category=ErrorCategory.UNRECOVERABLE,
            recovery_hint="check config",
        )
        assert err.category is ErrorCategory.UNRECOVERABLE
        assert err.recovery_hint == "check config"

    def test_message_preserved(self):
        """The error message should be accessible via str()."""
        err = IntelliSourceError(
            "oops",
            category=ErrorCategory.EXTERNAL,
            recovery_hint="wait",
        )
        assert "oops" in str(err)


# ---------------------------------------------------------------------------
# AC-T007a-2: ErrorCategory enum completeness and recovery strategies
# ---------------------------------------------------------------------------


class TestErrorCategory:
    """ErrorCategory enum must define exactly four members matching the architecture."""

    EXPECTED_MEMBERS = {
        "RECOVERABLE_TRANSIENT",
        "RECOVERABLE_DEGRADED",
        "UNRECOVERABLE",
        "EXTERNAL",
    }

    def test_enum_members_match_architecture(self):
        """Enum contains exactly the four categories defined in arch section 5.3."""
        actual = {member.name for member in ErrorCategory}
        assert actual == self.EXPECTED_MEMBERS

    def test_recovery_strategies_defined(self):
        """Each category must have a non-empty recovery strategy description."""
        for member in ErrorCategory:
            strategy = member.recovery_strategy
            assert isinstance(strategy, str) and len(strategy) > 0, (
                f"{member.name} missing recovery_strategy"
            )


# ---------------------------------------------------------------------------
# AC-T007a-3: Module-specific exception classes
# ---------------------------------------------------------------------------


_MODULE_ERROR_DEFAULTS = [
    (CollectorError, ErrorCategory.RECOVERABLE_TRANSIENT),
    (PipelineError, ErrorCategory.UNRECOVERABLE),
    (LLMError, ErrorCategory.RECOVERABLE_DEGRADED),
    (DistributorError, ErrorCategory.RECOVERABLE_TRANSIENT),
    (StorageError, ErrorCategory.UNRECOVERABLE),
]


class TestModuleErrors:
    """Each module error inherits IntelliSourceError with correct default category."""

    @pytest.mark.parametrize(
        "error_cls, expected_category",
        _MODULE_ERROR_DEFAULTS,
        ids=[cls.__name__ for cls, _ in _MODULE_ERROR_DEFAULTS],
    )
    def test_inherits_base(self, error_cls, expected_category):
        """Module error classes must be subclasses of IntelliSourceError."""
        assert issubclass(error_cls, IntelliSourceError)

    @pytest.mark.parametrize(
        "error_cls, expected_category",
        _MODULE_ERROR_DEFAULTS,
        ids=[cls.__name__ for cls, _ in _MODULE_ERROR_DEFAULTS],
    )
    def test_default_category(self, error_cls, expected_category):
        """Instantiating with just a message uses the predefined default category."""
        err = error_cls("test")
        assert err.category is expected_category

    @pytest.mark.parametrize(
        "error_cls, expected_category",
        _MODULE_ERROR_DEFAULTS,
        ids=[cls.__name__ for cls, _ in _MODULE_ERROR_DEFAULTS],
    )
    def test_category_overridable(self, error_cls, expected_category):
        """The default category should be overridable at instantiation time."""
        err = error_cls("test", category=ErrorCategory.EXTERNAL)
        assert err.category is ErrorCategory.EXTERNAL
