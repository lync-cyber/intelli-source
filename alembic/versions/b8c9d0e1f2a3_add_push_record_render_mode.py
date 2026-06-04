"""add render_mode to push_records

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "push_records",
        sa.Column("render_mode", sa.VARCHAR(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("push_records", "render_mode")
