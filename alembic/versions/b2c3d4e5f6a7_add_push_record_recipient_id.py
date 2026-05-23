"""add push_record recipient_id

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "push_records",
        sa.Column("recipient_id", sa.VARCHAR(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("push_records", "recipient_id")
