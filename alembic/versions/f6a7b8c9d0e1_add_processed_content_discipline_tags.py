"""add discipline_tags to processed_contents

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processed_contents",
        sa.Column(
            "discipline_tags",
            ARRAY(sa.String),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index(
        "ix_processed_contents_discipline_tags",
        "processed_contents",
        ["discipline_tags"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_processed_contents_discipline_tags",
        table_name="processed_contents",
    )
    op.drop_column("processed_contents", "discipline_tags")
