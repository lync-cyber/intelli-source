"""Model routing helpers: config loading, model resolution, error classification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from intellisource.core.errors import ErrorCategory, IntelliSourceError, LLMError
from intellisource.core.settings import get_settings
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_CONFIG_PATH = str(
    Path(__file__).resolve().parents[4] / "config" / "llm_models.yaml"
)

_TRANSIENT_EXCEPTION_NAMES = frozenset(
    [
        "Timeout",
        "APIConnectionError",
        "RateLimitError",
        "ServiceUnavailableError",
        "InternalServerError",
    ]
)

_UNRECOVERABLE_EXCEPTION_NAMES = frozenset(
    [
        "BadRequestError",
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "UnsupportedParamsError",
        "ContextWindowExceededError",
        "ContentPolicyViolationError",
    ]
)


def _classify_error(exc: BaseException) -> ErrorCategory:
    """Map an exception to an ErrorCategory for retry decisions.

    IntelliSourceError subclasses are classified by their own .category.
    litellm exceptions are classified by class name. Unknown exceptions
    default to RECOVERABLE_DEGRADED.
    """
    if isinstance(exc, IntelliSourceError):
        return exc.category

    exc_type_name = type(exc).__name__
    if exc_type_name in _TRANSIENT_EXCEPTION_NAMES:
        return ErrorCategory.RECOVERABLE_TRANSIENT
    if exc_type_name in _UNRECOVERABLE_EXCEPTION_NAMES:
        return ErrorCategory.UNRECOVERABLE
    return ErrorCategory.RECOVERABLE_DEGRADED


def _load_routing_config() -> dict[str, Any]:
    """Load model routing config from env var or default path.

    Falls back to an empty config if the file does not exist.
    """
    from intellisource.llm.model_config import load_model_config

    config_path = get_settings().llm_config_path or _DEFAULT_CONFIG_PATH
    path = Path(config_path)
    if not path.exists():
        logger.warning(
            "LLM routing config not found at '%s', using empty config",
            config_path,
        )
        return {
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
            "models": {},
            "profiles": {},
        }
    try:
        return load_model_config(config_path)
    except PydanticValidationError as exc:
        raise LLMError(
            f"LLM config validation failed: {exc}",
            category=ErrorCategory.UNRECOVERABLE,
        ) from exc
    except ValueError as exc:
        raise LLMError(
            f"LLM config file error: {exc}",
            category=ErrorCategory.UNRECOVERABLE,
        ) from exc
