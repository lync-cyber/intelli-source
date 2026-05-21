"""add timezone and discipline_tags

Revision ID: 62f6b6bf5177
Revises: 001
Create Date: 2026-05-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "62f6b6bf5177"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AC-1: Add timezone column to subscriptions
    op.add_column(
        "subscriptions",
        sa.Column(
            "timezone",
            sa.VARCHAR(100),
            nullable=False,
            server_default="Asia/Shanghai",
        ),
    )
    # AC-6: Add discipline_tags to subscriptions
    op.add_column(
        "subscriptions",
        sa.Column(
            "discipline_tags",
            ARRAY(sa.String),
            nullable=False,
            server_default="{}",
        ),
    )
    # AC-6: Add discipline_tags to sources
    op.add_column(
        "sources",
        sa.Column(
            "discipline_tags",
            ARRAY(sa.String),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("sources", "discipline_tags")
    op.drop_column("subscriptions", "discipline_tags")
    op.drop_column("subscriptions", "timezone")
