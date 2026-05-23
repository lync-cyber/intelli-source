"""add raw_content status and processed_at

Revision ID: a1b2c3d4e5f6
Revises: 62f6b6bf5177
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision = "a1b2c3d4e5f6"
down_revision = "62f6b6bf5177"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_contents",
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "raw_contents",
        sa.Column("processed_at", TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("raw_contents", "processed_at")
    op.drop_column("raw_contents", "status")
