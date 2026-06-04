"""add templates table

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.VARCHAR(255), nullable=False),
        sa.Column("base_template", sa.VARCHAR(100), nullable=False),
        sa.Column(
            "formats",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("default_format", sa.VARCHAR(20), nullable=False),
        sa.Column(
            "jinja_source",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "aggregate_config",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("name", name="uq_templates_name"),
    )
    op.create_index("ix_templates_status", "templates", ["status"])


def downgrade() -> None:
    op.drop_index("ix_templates_status", table_name="templates")
    op.drop_table("templates")
