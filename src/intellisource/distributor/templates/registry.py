"""TEMPLATE_REGISTRY: name -> DigestTemplate instance (mirrors PROCESSOR_REGISTRY)."""

from __future__ import annotations

from intellisource.distributor.templates.base import DigestTemplate

TEMPLATE_REGISTRY: dict[str, DigestTemplate] = {}


def register_template(template: DigestTemplate) -> None:
    """Register *template* under its ``name`` (last registration wins)."""
    TEMPLATE_REGISTRY[template.name] = template


def get_template(name: str) -> DigestTemplate:
    """Return the registered template for *name*, raising ValueError if unknown."""
    if name not in TEMPLATE_REGISTRY:
        raise ValueError(f"Unknown digest template: {name!r}")
    return TEMPLATE_REGISTRY[name]
