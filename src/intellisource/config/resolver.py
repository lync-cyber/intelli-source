"""Configuration layer merging: defaults → project → environment variables.

Priority (lowest → highest):
  1. config/defaults.yaml  (global defaults, version-controlled)
  2. config/llm_models.yaml  (project overrides)
  3. IS_* environment variables  (runtime overrides, highest priority)

Merge strategy: dict keys merged recursively; list values replaced wholesale.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

# Recognized top-level config keys.  Env vars that (after prefix stripping) do
# not begin with one of these keys are silently skipped to prevent accidental
# overwrite of unrelated environment variables.
_KNOWN_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {"default_model", "models", "profiles"}
)

# Secondary prefix that may be used instead of the raw IS_ prefix.
# IS_LLM_DEFAULT_MODEL → strip IS_LLM_ → DEFAULT_MODEL → default_model.model
_LLM_DOMAIN_PREFIX = "LLM_"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict that is *override* deep-merged onto *base*.

    - dict values: recursively merged.
    - All other values (including lists): override replaces base.
    """
    result: dict[str, Any] = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml_optional(path: str) -> dict[str, Any]:
    """Load a YAML file; return empty dict if file is absent.

    Raises:
        ValueError: If the file is present but contains malformed YAML.
    """
    file_path = Path(path)
    if not file_path.exists():
        logger.info("Config file not found, skipping: %s", path)
        return {}
    text = file_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML config file {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")
    return dict(data)


def _normalize_env_key(raw_key: str, prefix_upper: str) -> str | None:
    """Strip env-var prefix and return the lower-cased remainder.

    Handles two prefix forms:
      1. ``IS_LLM_DEFAULT_MODEL``  → strip ``IS_LLM_`` → ``default_model``
      2. ``IS_DEFAULT_MODEL_MODEL`` → strip ``IS_`` → ``default_model_model``

    Returns ``None`` if the remainder does not begin with a known top-level key
    (whitelist guard).
    """
    remainder = raw_key[len(prefix_upper) :].lower()

    # Try stripping optional domain prefix (e.g. "llm_").
    domain_prefix_lower = _LLM_DOMAIN_PREFIX.lower()
    if remainder.startswith(domain_prefix_lower):
        candidate = remainder[len(domain_prefix_lower) :]
        # Accept if candidate begins with a known top-level key.
        if any(
            candidate == k or candidate.startswith(k + "_")
            for k in _KNOWN_TOP_LEVEL_KEYS
        ):
            return candidate

    # Accept plain remainder if it begins with a known top-level key.
    if any(
        remainder == k or remainder.startswith(k + "_") for k in _KNOWN_TOP_LEVEL_KEYS
    ):
        return remainder

    logger.debug("Env var %s does not map to a known config section; skipped", raw_key)
    return None


def _apply_env_vars(config: dict[str, Any], prefix: str) -> dict[str, Any]:
    """Apply IS_* (or custom-prefix) env vars onto *config* in-place copy.

    Env var naming conventions (both are supported):
      IS_LLM_DEFAULT_MODEL       → config["default_model"]["model"]
      IS_DEFAULT_MODEL_MODEL     → config["default_model"]["model"]
      IS_LLM_MODELS_EXTRACT_MODEL → config["models"]["extract"]["model"]
      IS_DEFAULT_MODEL_PROVIDER  → config["default_model"]["provider"]

    Only env vars whose names (after prefix stripping) map to a known top-level
    key (default_model, models, profiles) are processed; all others are ignored.
    """
    result: dict[str, Any] = dict(config)
    prefix_upper = prefix.upper()

    for raw_key, value in os.environ.items():
        if not raw_key.upper().startswith(prefix_upper):
            continue
        normalized = _normalize_env_key(raw_key, prefix_upper)
        if normalized is None:
            continue
        parts = normalized.split("_")
        _set_nested(result, parts, value, raw_key)

    return result


def _set_nested(
    config: dict[str, Any],
    parts: list[str],
    value: str,
    raw_key: str = "",
) -> None:
    """Set a value in *config* by resolving *parts* against the existing keys.

    Walks the config tree greedily: at each level it tries the longest prefix
    of remaining parts that matches an existing key, then recurses.  This
    handles top-level keys whose names contain underscores (e.g. "default_model").

    Non-dict leaf targets are *not* overwritten; a warning is logged instead.
    """
    if not parts:
        return

    # Try to match a key using 1..len(parts) segments (greedy first).
    for end in range(len(parts), 0, -1):
        candidate = "_".join(parts[:end])
        if candidate not in config:
            continue
        remaining = parts[end:]
        if not remaining:
            if isinstance(config[candidate], dict) and end > 1:
                # The greedy match consumed all parts but landed on a dict
                # section — the env var intends to set a field *inside* that
                # section.  Split off the last segment and recurse so it
                # becomes the leaf key within the section.
                # Example: parts=["default","model"], candidate="default_model"
                # (dict) → recurse into config["default_model"] with ["model"].
                shorter_candidate = "_".join(parts[: end - 1])
                if shorter_candidate in config and isinstance(
                    config[shorter_candidate], dict
                ):
                    _set_nested(
                        config[shorter_candidate], parts[end - 1 :], value, raw_key
                    )
                else:
                    _set_nested(config[candidate], [parts[end - 1]], value, raw_key)
                return
            # Scalar leaf assignment (or dict overwrite when len(parts)==1,
            # which is intentional: single-segment env var targets the key directly).
            config[candidate] = value
        elif isinstance(config[candidate], dict):
            _set_nested(config[candidate], remaining, value, raw_key)
        else:
            # Target exists but is not a dict; refuse to overwrite to
            # prevent accidental field corruption via env var naming collision.
            logger.warning(
                "Env var %s targets non-dict path %s; skipped to prevent"
                " unintended overwrite",
                raw_key,
                candidate,
            )
        return

    # No existing key matched; create nested structure: all-but-last as parent
    # key (joined with "_"), last segment as leaf.
    if len(parts) >= 2:
        parent_key = "_".join(parts[:-1])
        leaf_key = parts[-1]
        if parent_key not in config:
            config[parent_key] = {}
        if isinstance(config[parent_key], dict):
            config[parent_key][leaf_key] = value
        else:
            config[parent_key] = {leaf_key: value}
    else:
        config[parts[0]] = value


class ConfigResolver:
    """Resolves configuration by merging defaults, project overrides, and env vars.

    AC-T059-6 compliance note: Pydantic schema validation is the caller's
    responsibility.  Pass a ``validator`` callable to enforce schema at
    resolve time; the resolver itself is schema-agnostic so it can serve
    both LLM and source configurations.
    """

    def __init__(
        self,
        defaults_path: str,
        project_path: str,
        env_prefix: str = "IS_",
        validator: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._defaults_path = defaults_path
        self._project_path = project_path
        self._env_prefix = env_prefix
        self._validator = validator

    def resolve(self) -> dict[str, Any]:
        """Return the fully merged configuration dict.

        Layer order (lowest → highest priority):
          1. defaults_path YAML
          2. project_path YAML
          3. env vars with *env_prefix*

        If a *validator* was provided at construction time, it is called with
        the merged dict before returning.  Any exception raised by the validator
        propagates to the caller unchanged.

        Raises:
            ValueError: If any YAML file is present but malformed.
        """
        defaults = _load_yaml_optional(self._defaults_path)
        project = _load_yaml_optional(self._project_path)

        merged = _deep_merge(defaults, project)
        merged = _apply_env_vars(merged, self._env_prefix)

        if self._validator is not None:
            self._validator(merged)

        return merged
