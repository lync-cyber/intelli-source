"""add subscription_config_versions table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_config_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Text(), nullable=False, unique=True),
        sa.Column("snapshot_yaml", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_subscription_config_versions_version",
        "subscription_config_versions",
        ["version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscription_config_versions_version",
        table_name="subscription_config_versions",
    )
    op.drop_table("subscription_config_versions")
