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
from typing import Any

import yaml

logger = logging.getLogger(__name__)


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
    """Load a YAML file; return empty dict if file is absent."""
    file_path = Path(path)
    if not file_path.exists():
        logger.info("Config file not found, skipping: %s", path)
        return {}
    text = file_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")
    return dict(data)


def _apply_env_vars(config: dict[str, Any], prefix: str) -> dict[str, Any]:
    """Apply IS_* (or custom-prefix) env vars onto *config* in-place copy.

    Env var naming convention (Option A — flat top-level structure):
      IS_<SECTION>_<KEY>  →  config[section][key]

    Examples:
      IS_DEFAULT_MODEL_MODEL     → config["default_model"]["model"]
      IS_DEFAULT_MODEL_PROVIDER  → config["default_model"]["provider"]

    The env var name (after stripping the prefix) is lower-cased then split on
    the first underscore that separates a top-level key from its sub-key.
    The algorithm walks the existing config to find the deepest matching path.
    """
    result: dict[str, Any] = dict(config)
    prefix_upper = prefix.upper()

    for raw_key, value in os.environ.items():
        if not raw_key.upper().startswith(prefix_upper):
            continue
        # Strip prefix and lower-case the remainder.
        stripped = raw_key[len(prefix_upper) :].lower()
        # Split into segments; try progressively longer top-level keys.
        parts = stripped.split("_")
        _set_nested(result, parts, value)

    return result


def _set_nested(config: dict[str, Any], parts: list[str], value: str) -> None:
    """Set a value in *config* by resolving *parts* against the existing keys.

    Walks the config tree greedily: at each level it tries the longest prefix
    of remaining parts that matches an existing key, then recurses.  This
    handles top-level keys whose names contain underscores (e.g. "default_model").
    """
    if not parts:
        return

    # Try to match a key using 1..len(parts) segments.
    for end in range(len(parts), 0, -1):
        candidate = "_".join(parts[:end])
        if candidate in config:
            remaining = parts[end:]
            if not remaining:
                # Leaf assignment — keep as string (simplest safe conversion).
                config[candidate] = value
            elif isinstance(config[candidate], dict):
                _set_nested(config[candidate], remaining, value)
            else:
                # Target exists but is not a dict; overwrite with string.
                config[candidate] = value
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
    """Resolves configuration by merging defaults, project overrides, and env vars."""

    def __init__(
        self,
        defaults_path: str,
        project_path: str,
        env_prefix: str = "IS_",
    ) -> None:
        self._defaults_path = defaults_path
        self._project_path = project_path
        self._env_prefix = env_prefix

    def resolve(self) -> dict[str, Any]:
        """Return the fully merged configuration dict.

        Layer order (lowest → highest priority):
          1. defaults_path YAML
          2. project_path YAML
          3. env vars with *env_prefix*
        """
        defaults = _load_yaml_optional(self._defaults_path)
        project = _load_yaml_optional(self._project_path)

        merged = _deep_merge(defaults, project)
        merged = _apply_env_vars(merged, self._env_prefix)

        return merged
