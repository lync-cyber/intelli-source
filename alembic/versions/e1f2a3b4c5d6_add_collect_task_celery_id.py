"""add celery_task_id to collect_tasks

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collect_tasks",
        sa.Column("celery_task_id", sa.VARCHAR(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("collect_tasks", "celery_task_id")
