"""Digest output templates: aggregation + render model + registry.

Importing this package registers all built-in templates into
``TEMPLATE_REGISTRY``. Use ``get_template(name)`` to resolve one.
"""

from typing import Any

# Importing the builtin package registers the default templates as a side effect.
import intellisource.distributor.templates.builtin  # noqa: E402,F401
from intellisource.distributor.templates.base import DigestTemplate
from intellisource.distributor.templates.registry import (
    TEMPLATE_REGISTRY,
    get_template,
    register_template,
)

# Snapshot of the built-in template names, captured right after the builtin
# package import registers them (and before any DB template is hydrated in), so
# it always reflects the built-ins only — used to validate a custom template's
# ``base_template`` reference.
BUILTIN_TEMPLATE_NAMES: frozenset[str] = frozenset(TEMPLATE_REGISTRY)


def resolve_template_for(
    channel_config: dict[str, Any] | None,
    *,
    default: str,
) -> tuple[DigestTemplate, dict[str, Any]]:
    """Pick the template named in ``channel_config['template']`` (falling back to
    *default* when absent or unknown) and return it with its ``template_config``."""
    cfg = channel_config or {}
    name = cfg.get("template") or default
    try:
        template = get_template(name)
    except ValueError:
        template = get_template(default)
    return template, dict(cfg.get("template_config") or {})


__all__ = [
    "BUILTIN_TEMPLATE_NAMES",
    "TEMPLATE_REGISTRY",
    "DigestTemplate",
    "get_template",
    "register_template",
    "resolve_template_for",
]
