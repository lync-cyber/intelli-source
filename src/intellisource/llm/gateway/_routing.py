"""Model routing helpers: config loading, model resolution, error classification."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError as PydanticValidationError

from intellisource.core.errors import ErrorCategory, IntelliSourceError, LLMError
from intellisource.core.settings import get_settings
from intellisource.observability.logging import get_logger

if TYPE_CHECKING:
    from intellisource.llm.model_config import ModelProfile, ModelRoutingConfig

logger = get_logger(__name__)


def resolve_model(
    routing_config: dict[str, Any],
    model: str | None,
    task_type: str | None,
    *,
    warn: Any = None,
    fallback_default: bool = False,
) -> str:
    """Resolve the litellm model id from explicit model / task routing / defaults.

    - explicit ``model`` always wins.
    - ``task_type`` mapped in routing config → that model.
    - ``task_type`` set but unmapped → ``default_model`` (calling ``warn`` first
      when a warn callable is supplied, so complete() keeps its warning while
      stream stays quiet).
    - no ``task_type`` → ``default_model`` when ``fallback_default`` is True
      (streaming path), otherwise the ``"gpt-4o-mini"`` safety net.
    """
    if model is not None:
        return model
    models = routing_config.get("models", {})
    if task_type is not None:
        if task_type in models:
            return cast(str, models[task_type]["model"])
        if warn is not None:
            warn("No model config for task_type '%s', using default_model", task_type)
        return cast(str, routing_config["default_model"]["model"])
    if fallback_default:
        return cast(str, routing_config["default_model"]["model"])
    return "gpt-4o-mini"


def resolve_call_params(
    model_routing: ModelRoutingConfig,
    model: str,
    temperature: float | None,
    max_tokens: int | None,
    default_temperature: float,
    default_max_tokens: int,
    task_cfg: dict[str, Any] | None = None,
) -> tuple[ModelProfile | None, float, int]:
    """Resolve (profile, temperature, max_tokens) for a model.

    Precedence, first non-None wins: explicit caller arg → task-level config
    (``models[task_type]``) → model profile → gateway default. This matches the
    thinking / reasoning_effort precedence in :func:`build_extra_body`.
    """
    profile = model_routing.get_profile(model)
    overrides = task_cfg or {}
    resolved_temperature = temperature
    if resolved_temperature is None:
        resolved_temperature = overrides.get("temperature")
    if resolved_temperature is None:
        resolved_temperature = (
            profile.temperature if profile is not None else default_temperature
        )
    resolved_max_tokens = max_tokens
    if resolved_max_tokens is None:
        resolved_max_tokens = overrides.get("max_tokens")
    if resolved_max_tokens is None:
        resolved_max_tokens = (
            profile.max_tokens if profile is not None else default_max_tokens
        )
    return profile, resolved_temperature, resolved_max_tokens


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


async def run_with_model_failover(
    models_to_try: list[str],
    call_one: Callable[[str], Awaitable[Any]],
    *,
    on_failure: Callable[[str, BaseException], None] | None = None,
) -> tuple[Any, str]:
    """Run ``call_one`` over models in order; return (result, model) on success.

    ``call_one`` runs one model end to end and owns that model's own transient
    retries, so reaching the next candidate means the current one is genuinely
    unavailable. An UNRECOVERABLE error (malformed / unsupported request) fails
    identically on every model, so it stops the sweep early. ``on_failure`` is
    invoked per failed candidate (e.g. to record a failure metric). When every
    candidate fails the last exception is re-raised.
    """
    last_exc: BaseException | None = None
    for candidate in models_to_try:
        try:
            result = await call_one(candidate)
            return result, candidate
        except asyncio.CancelledError:
            raise  # cancellation must propagate, never fall over to another model
        except BaseException as exc:
            if on_failure is not None:
                on_failure(candidate, exc)
            last_exc = exc
            if _classify_error(exc) is ErrorCategory.UNRECOVERABLE:
                break
    if last_exc is None:
        raise LLMError(
            "run_with_model_failover called with no models to try",
            category=ErrorCategory.UNRECOVERABLE,
        )
    raise last_exc


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
