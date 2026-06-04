"""add pipelines + pipeline_steps tables

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipelines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.VARCHAR(100), nullable=False),
        sa.Column("mode", sa.VARCHAR(20), nullable=False),
        sa.Column(
            "max_steps", sa.Integer(), nullable=False, server_default=sa.text("50")
        ),
        sa.Column(
            "on_failure",
            sa.VARCHAR(20),
            nullable=False,
            server_default=sa.text("'abort'"),
        ),
        sa.Column(
            "agent_mode",
            sa.VARCHAR(20),
            nullable=False,
            server_default=sa.text("'process'"),
        ),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("max_tokens_budget", sa.Integer(), nullable=True),
        sa.Column(
            "tools_allowed",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "tools_denied",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "tool_permissions",
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
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("name", name="uq_pipelines_name"),
    )
    op.create_index("ix_pipelines_status", "pipelines", ["status"])

    op.create_table(
        "pipeline_steps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_id", UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "definition",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "pipeline_id", "position", name="uq_pipeline_steps_position"
        ),
    )
    op.create_index("ix_pipeline_steps_pipeline_id", "pipeline_steps", ["pipeline_id"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_steps_pipeline_id", table_name="pipeline_steps")
    op.drop_table("pipeline_steps")
    op.drop_index("ix_pipelines_status", table_name="pipelines")
    op.drop_table("pipelines")
