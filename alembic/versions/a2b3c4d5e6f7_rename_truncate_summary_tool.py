"""rename truncate_summary tool to summarize_cluster

Rewrites persisted pipeline definitions so existing rows keep resolving the
cluster-digest tool after it was renamed from ``truncate_summary`` to
``summarize_cluster``: the name appears in ``pipelines.tools_allowed`` /
``tools_denied`` (JSONB string arrays) and may appear as a key in
``pipelines.tool_permissions`` (JSONB object). Immutable ``config_versions``
YAML snapshots are intentionally left untouched (point-in-time history).

Revision ID: a2b3c4d5e6f7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None

_OLD = "truncate_summary"
_NEW = "summarize_cluster"


def _rewrite(old: str, new: str) -> None:
    # Replace the element inside the two JSONB string arrays.
    for column in ("tools_allowed", "tools_denied"):
        op.execute(
            f"""
            UPDATE pipelines
            SET {column} = (
                SELECT COALESCE(
                    jsonb_agg(
                        CASE WHEN elem = to_jsonb('{old}'::text)
                             THEN to_jsonb('{new}'::text)
                             ELSE elem END
                    ),
                    '[]'::jsonb
                )
                FROM jsonb_array_elements({column}) AS elem
            )
            WHERE {column} @> '["{old}"]'::jsonb
            """
        )
    # Rename the key inside the JSONB tool_permissions object, if present.
    op.execute(
        f"""
        UPDATE pipelines
        SET tool_permissions =
            (tool_permissions - '{old}')
            || jsonb_build_object('{new}', tool_permissions -> '{old}')
        WHERE tool_permissions ? '{old}'
        """
    )


def upgrade() -> None:
    _rewrite(_OLD, _NEW)


def downgrade() -> None:
    _rewrite(_NEW, _OLD)
