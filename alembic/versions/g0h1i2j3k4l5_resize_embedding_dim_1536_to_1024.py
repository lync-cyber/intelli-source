"""resize embedding vector columns from 1536 to 1024

Revision ID: g0h1i2j3k4l5
Revises: a2b3c4d5e6f7
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op
from pgvector.sqlalchemy import Vector

revision = "g0h1i2j3k4l5"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # processed_contents.embedding: resize 1536 → 1024
    op.drop_index(
        "ix_processed_contents_embedding",
        table_name="processed_contents",
    )
    op.alter_column(
        "processed_contents",
        "embedding",
        type_=Vector(1024),
        existing_nullable=True,
    )
    op.create_index(
        "ix_processed_contents_embedding",
        "processed_contents",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # content_clusters.centroid: resize 1536 → 1024
    op.alter_column(
        "content_clusters",
        "centroid",
        type_=Vector(1024),
        existing_nullable=True,
    )


def downgrade() -> None:
    # content_clusters.centroid: revert 1024 → 1536
    op.alter_column(
        "content_clusters",
        "centroid",
        type_=Vector(1536),
        existing_nullable=True,
    )

    # processed_contents.embedding: revert 1024 → 1536
    op.drop_index(
        "ix_processed_contents_embedding",
        table_name="processed_contents",
    )
    op.alter_column(
        "processed_contents",
        "embedding",
        type_=Vector(1536),
        existing_nullable=True,
    )
    op.create_index(
        "ix_processed_contents_embedding",
        "processed_contents",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
