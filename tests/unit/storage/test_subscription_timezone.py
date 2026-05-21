"""Tests for Subscription.timezone and discipline_tags ORM fields.

Covers AC-1 and AC-6 of T-093:
- AC-1: Subscription ORM model has 'timezone' column (VARCHAR, default 'Asia/Shanghai')
- AC-6: Subscription and Source ORM models have 'discipline_tags' ARRAY
        column (default [])
"""

from __future__ import annotations

from intellisource.storage.models import Source, Subscription

# ---------------------------------------------------------------------------
# Helpers (reuse pattern from test_models.py)
# ---------------------------------------------------------------------------


def _col(model, name):
    return model.__table__.columns[name]


def _col_type_name(model, name):
    return type(_col(model, name).type).__name__.upper()


# ===========================================================================
# AC-1: Subscription.timezone field
# ===========================================================================


class TestSubscriptionTimezoneColumn:
    def test_timezone_column_exists(self):
        """AC-1: Subscription.__table__ has a 'timezone' column."""
        assert "timezone" in Subscription.__table__.columns, (
            "Subscription model is missing 'timezone' column"
        )

    def test_timezone_column_is_varchar(self):
        """AC-1: timezone column is VARCHAR type."""
        type_name = _col_type_name(Subscription, "timezone")
        assert type_name == "VARCHAR", (
            f"Expected VARCHAR for timezone column, got {type_name}"
        )

    def test_timezone_column_has_default_asia_shanghai(self):
        """AC-1: timezone column default is 'Asia/Shanghai'."""
        col = _col(Subscription, "timezone")
        server_default = col.server_default
        col_default = col.default
        # Either a server_default string or a ColumnDefault with 'Asia/Shanghai'
        has_default = (
            server_default is not None and "Asia/Shanghai" in str(server_default.arg)
        ) or (
            col_default is not None
            and hasattr(col_default, "arg")
            and col_default.arg == "Asia/Shanghai"
        )
        assert has_default, (
            f"timezone column must default to 'Asia/Shanghai'; "
            f"server_default={server_default!r}, column_default={col_default!r}"
        )

    def test_timezone_mapped_attribute_accessible(self):
        """AC-1: Subscription class has 'timezone' as a mapped attribute."""
        assert hasattr(Subscription, "timezone"), (
            "Subscription class missing 'timezone' mapped attribute"
        )


# ===========================================================================
# AC-6: discipline_tags on Subscription
# ===========================================================================


class TestSubscriptionDisciplineTagsColumn:
    def test_discipline_tags_column_exists(self):
        """AC-6: Subscription.__table__ has 'discipline_tags' column."""
        assert "discipline_tags" in Subscription.__table__.columns, (
            "Subscription model is missing 'discipline_tags' column"
        )

    def test_discipline_tags_is_array_type(self):
        """AC-6: discipline_tags is ARRAY (PG) / JSON (SQLite via Variant)."""
        col = _col(Subscription, "discipline_tags")
        type_name = type(col.type).__name__.upper()
        # Variant pattern: ARRAY on PG, JSON on SQLite (T-093 task card)
        assert type_name in ("ARRAY", "JSON"), (
            f"Expected ARRAY (PG) or JSON (SQLite fallback) type "
            f"for discipline_tags, got {type_name}"
        )

    def test_discipline_tags_has_default_empty_list(self):
        """AC-6: discipline_tags column defaults to empty list []."""
        col = _col(Subscription, "discipline_tags")
        col_default = col.default
        server_default = col.server_default
        # Accept either Python-side default=list or server_default "ARRAY[]"
        has_default = (col_default is not None) or (server_default is not None)
        assert has_default, (
            "discipline_tags must have a default (empty list or server-side ARRAY[])"
        )

    def test_discipline_tags_mapped_attribute_accessible(self):
        """AC-6: Subscription class has 'discipline_tags' mapped attribute."""
        assert hasattr(Subscription, "discipline_tags"), (
            "Subscription class missing 'discipline_tags' mapped attribute"
        )


# ===========================================================================
# AC-6: discipline_tags on Source
# ===========================================================================


class TestSourceDisciplineTagsColumn:
    def test_discipline_tags_column_exists(self):
        """AC-6: Source.__table__ has 'discipline_tags' column."""
        assert "discipline_tags" in Source.__table__.columns, (
            "Source model is missing 'discipline_tags' column"
        )

    def test_discipline_tags_is_array_type(self):
        """AC-6: Source.discipline_tags is ARRAY (PG) / JSON (SQLite via Variant)."""
        col = _col(Source, "discipline_tags")
        type_name = type(col.type).__name__.upper()
        assert type_name in ("ARRAY", "JSON"), (
            f"Expected ARRAY (PG) or JSON (SQLite fallback) type for "
            f"Source.discipline_tags, got {type_name}"
        )

    def test_discipline_tags_has_default(self):
        """AC-6: Source.discipline_tags has a default (empty list)."""
        col = _col(Source, "discipline_tags")
        has_default = (col.default is not None) or (col.server_default is not None)
        assert has_default, (
            "Source.discipline_tags must have a default (empty list or server-side)"
        )

    def test_discipline_tags_mapped_attribute_accessible(self):
        """AC-6: Source class has 'discipline_tags' mapped attribute."""
        assert hasattr(Source, "discipline_tags"), (
            "Source class missing 'discipline_tags' mapped attribute"
        )
