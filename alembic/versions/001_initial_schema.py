"""Initial schema - create all 11 ORM tables.

Revision ID: 001
Revises:
Create Date: 2026-04-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS zhparser")
    # Create a text-search configuration named `zhparser` that uses the
    # zhparser parser. storage/vector.py references this configuration in
    # `to_tsvector('zhparser', ...)` / `websearch_to_tsquery('zhparser', :q)`.
    # PostgreSQL has no IF NOT EXISTS for TEXT SEARCH CONFIGURATION, so guard
    # via pg_ts_config catalog lookup for idempotent reruns.
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'zhparser') THEN "
        "CREATE TEXT SEARCH CONFIGURATION zhparser (PARSER = zhparser); "
        "ALTER TEXT SEARCH CONFIGURATION zhparser ADD MAPPING FOR "
        "n,v,a,i,e,l,j WITH simple; "
        "END IF; "
        "END $$"
    )

    # E-001: sources
    op.create_table(
        "sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.VARCHAR(255), nullable=False, unique=True),
        sa.Column("type", sa.VARCHAR(20), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("tags", JSONB, nullable=False),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active"),
        sa.Column(
            "schedule_interval", sa.Integer, nullable=False, server_default="3600"
        ),
        sa.Column(
            "schedule_adaptive", sa.Boolean, nullable=False, server_default="true"
        ),
        sa.Column("proxy", sa.VARCHAR(255), nullable=True),
        sa.Column("rate_limit_qps", sa.Numeric, nullable=True),
        sa.Column("rate_limit_concurrency", sa.Integer, nullable=True),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("last_collected_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_collect_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_update_interval", sa.Integer, nullable=True),
        sa.Column("http_etag", sa.VARCHAR(255), nullable=True),
        sa.Column("http_last_modified", sa.VARCHAR(255), nullable=True),
        sa.Column("config_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_sources_status", "sources", ["status"])
    op.create_index("ix_sources_next_collect_at", "sources", ["next_collect_at"])
    op.create_index("ix_sources_tags", "sources", ["tags"], postgresql_using="gin")

    # E-008: task_chains
    op.create_table(
        "task_chains",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_name", sa.VARCHAR(100), nullable=False),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="pending"),
        sa.Column("trigger_type", sa.VARCHAR(20), nullable=False),
        sa.Column("execution_mode", sa.VARCHAR(20), nullable=False),
        sa.Column("total_steps", sa.Integer, nullable=False),
        sa.Column("completed_steps", sa.Integer, nullable=False, server_default="0"),
        sa.Column("current_step", sa.VARCHAR(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_task_chains_status", "task_chains", ["status"])
    op.create_index("ix_task_chains_pipeline_name", "task_chains", ["pipeline_name"])

    # E-002: collect_tasks
    op.create_table(
        "collect_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id", UUID(as_uuid=True), sa.ForeignKey("sources.id"), nullable=False
        ),
        sa.Column(
            "task_chain_id",
            UUID(as_uuid=True),
            sa.ForeignKey("task_chains.id"),
            nullable=True,
        ),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.VARCHAR(20), nullable=False, server_default="normal"),
        sa.Column("trigger_type", sa.VARCHAR(20), nullable=False),
        sa.Column("items_collected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_collect_tasks_status", "collect_tasks", ["status"])
    op.create_index("ix_collect_tasks_source_id", "collect_tasks", ["source_id"])
    op.create_index(
        "ix_collect_tasks_task_chain_id", "collect_tasks", ["task_chain_id"]
    )

    # E-003: raw_contents
    op.create_table(
        "raw_contents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id", UUID(as_uuid=True), sa.ForeignKey("sources.id"), nullable=False
        ),
        sa.Column(
            "collect_task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("collect_tasks.id"),
            nullable=True,
        ),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("author", sa.VARCHAR(255), nullable=True),
        sa.Column("body_html", sa.Text, nullable=True),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("published_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("fingerprint", sa.VARCHAR(64), nullable=False, unique=True),
        sa.Column("raw_metadata", JSONB, nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_raw_contents_fingerprint", "raw_contents", ["fingerprint"])
    op.create_index("ix_raw_contents_source_id", "raw_contents", ["source_id"])
    op.create_index("ix_raw_contents_published_at", "raw_contents", ["published_at"])

    # E-005: content_clusters
    op.create_table(
        "content_clusters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("tags", JSONB, nullable=False),
        sa.Column("content_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("centroid", Vector(1536), nullable=True),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_content_clusters_tags", "content_clusters", ["tags"], postgresql_using="gin"
    )
    op.create_index(
        "ix_content_clusters_updated_at", "content_clusters", ["updated_at"]
    )

    # E-004: processed_contents
    op.create_table(
        "processed_contents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "raw_content_id",
            UUID(as_uuid=True),
            sa.ForeignKey("raw_contents.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("tags", JSONB, nullable=False),
        sa.Column(
            "cluster_id",
            UUID(as_uuid=True),
            sa.ForeignKey("content_clusters.id"),
            nullable=True,
        ),
        sa.Column("fingerprint", sa.VARCHAR(64), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("structured_data", JSONB, nullable=True),
        sa.Column(
            "processing_status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("processed_by", sa.VARCHAR(20), nullable=False, server_default="llm"),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("source_name", sa.VARCHAR(255), nullable=True),
        sa.Column("published_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("processed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_processed_contents_processing_status",
        "processed_contents",
        ["processing_status"],
    )
    op.create_index(
        "ix_processed_contents_cluster_id", "processed_contents", ["cluster_id"]
    )
    op.create_index(
        "ix_processed_contents_tags",
        "processed_contents",
        ["tags"],
        postgresql_using="gin",
    )
    op.execute(
        "CREATE INDEX ix_processed_contents_embedding ON processed_contents "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_index(
        "ix_processed_contents_published_at", "processed_contents", ["published_at"]
    )
    op.execute(
        "CREATE INDEX ix_processed_contents_fts ON processed_contents "
        "USING gin (body_text gin_trgm_ops)"
    )

    # E-006: digests
    op.create_table(
        "digests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cluster_id",
            UUID(as_uuid=True),
            sa.ForeignKey("content_clusters.id"),
            nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("timeline", JSONB, nullable=True),
        sa.Column("key_points", JSONB, nullable=False),
        sa.Column("generated_by", sa.VARCHAR(20), nullable=False, server_default="llm"),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_digests_cluster_id", "digests", ["cluster_id"])

    # E-007: llm_call_logs
    op.create_table(
        "llm_call_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("model", sa.VARCHAR(100), nullable=False),
        sa.Column("provider", sa.VARCHAR(50), nullable=False),
        sa.Column("call_type", sa.VARCHAR(50), nullable=False),
        sa.Column(
            "content_id",
            UUID(as_uuid=True),
            sa.ForeignKey("processed_contents.id"),
            nullable=True,
        ),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("input_length", sa.Integer, nullable=False),
        sa.Column("output_length", sa.Integer, nullable=False),
        sa.Column("status", sa.VARCHAR(20), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_attempt", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_llm_call_logs_model", "llm_call_logs", ["model"])
    op.create_index("ix_llm_call_logs_created_at", "llm_call_logs", ["created_at"])
    op.create_index("ix_llm_call_logs_call_type", "llm_call_logs", ["call_type"])
    op.create_index("ix_llm_call_logs_content_id", "llm_call_logs", ["content_id"])

    # E-009: subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.VARCHAR(255), nullable=False),
        sa.Column(
            "source_id", UUID(as_uuid=True), sa.ForeignKey("sources.id"), nullable=True
        ),
        sa.Column("channel", sa.VARCHAR(20), nullable=False),
        sa.Column("channel_config", JSONB, nullable=False),
        sa.Column("match_rules", JSONB, nullable=False),
        sa.Column(
            "frequency", sa.VARCHAR(20), nullable=False, server_default="realtime"
        ),
        sa.Column("quiet_hours", JSONB, nullable=True),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_subscriptions_channel", "subscriptions", ["channel"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])
    op.create_index(
        "ix_subscriptions_match_rules",
        "subscriptions",
        ["match_rules"],
        postgresql_using="gin",
    )

    # E-010: push_records
    op.create_table(
        "push_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subscription_id",
            UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id"),
            nullable=False,
        ),
        sa.Column(
            "content_id",
            UUID(as_uuid=True),
            sa.ForeignKey("processed_contents.id"),
            nullable=False,
        ),
        sa.Column("channel", sa.VARCHAR(20), nullable=False),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("sent_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("delivered_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "subscription_id", "content_id", "channel", name="uq_push_records_dedup"
        ),
    )
    op.create_index(
        "ix_push_records_subscription_id", "push_records", ["subscription_id"]
    )
    op.create_index("ix_push_records_content_id", "push_records", ["content_id"])

    # E-011: chat_sessions
    op.create_table(
        "chat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.VARCHAR(20), nullable=False),
        sa.Column("channel_user_id", sa.VARCHAR(255), nullable=False),
        sa.Column("context", JSONB, nullable=False),
        sa.Column("last_active_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_chat_sessions_user", "chat_sessions", ["channel", "channel_user_id"]
    )
    op.create_index(
        "ix_chat_sessions_last_active_at", "chat_sessions", ["last_active_at"]
    )


def downgrade() -> None:
    op.drop_table("chat_sessions")
    op.drop_table("push_records")
    op.drop_table("subscriptions")
    op.drop_table("llm_call_logs")
    op.drop_table("digests")
    op.drop_table("processed_contents")
    op.drop_table("content_clusters")
    op.drop_table("raw_contents")
    op.drop_table("collect_tasks")
    op.drop_table("task_chains")
    op.drop_table("sources")

    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS zhparser")
    op.execute("DROP EXTENSION IF EXISTS zhparser")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
