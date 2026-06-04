"""P1-b: built-in name snapshot + DB-template registry hydration."""

from __future__ import annotations

from types import SimpleNamespace

from intellisource.distributor.templates import (
    BUILTIN_TEMPLATE_NAMES,
    TEMPLATE_REGISTRY,
    get_template,
)
from intellisource.distributor.templates.db_template import (
    DbDigestTemplate,
    db_template_from_row,
    register_db_templates,
)


def _row(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        formats=["markdown"],
        default_format="markdown",
        base_template="daily-brief",
        jinja_source={"markdown": "x"},
        aggregate_config={},
    )


def test_builtin_names_snapshot_contains_the_five_builtins() -> None:
    assert {
        "daily-brief",
        "weekly-roundup",
        "topic-deepdive",
        "push-card",
        "json-feed",
    } <= set(BUILTIN_TEMPLATE_NAMES)


def test_db_template_from_row_builds_adapter() -> None:
    tpl = db_template_from_row(_row("x-tpl"))
    assert isinstance(tpl, DbDigestTemplate)
    assert tpl.name == "x-tpl"
    assert tpl.formats == frozenset({"markdown"})


def test_register_db_templates_makes_them_resolvable() -> None:
    name = "zzz-hydration-test-template"
    try:
        count = register_db_templates([_row(name)])
        assert count == 1
        resolved = get_template(name)
        assert isinstance(resolved, DbDigestTemplate)
        assert resolved.name == name
    finally:
        TEMPLATE_REGISTRY.pop(name, None)
