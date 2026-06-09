"""ORM model definitions for all entities (T-003).

Defines the SQLAlchemy 2.0 mapped models for every persisted entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import VARCHAR

EMBEDDING_DIM: int = 1024


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------


class CreatedAtMixin:
    """Adds created_at with a server-side default of now()."""

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class TimestampMixin(CreatedAtMixin):
    """Adds created_at (server default now) and updated_at (on-update now)."""

    updated_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, onupdate=func.now()
    )


class ExecutionTimingMixin:
    """Adds started_at and finished_at for executable entities."""

    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# E-001: Source
# ---------------------------------------------------------------------------


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(VARCHAR(255), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, default="active")
    schedule_interval: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3600
    )
    schedule_adaptive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    proxy: Mapped[Optional[str]] = mapped_column(VARCHAR(255), nullable=True)
    rate_limit_qps: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    rate_limit_concurrency: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    last_collected_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    next_collect_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_update_interval: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    http_etag: Mapped[Optional[str]] = mapped_column(VARCHAR(255), nullable=True)
    http_last_modified: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), nullable=True
    )
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    discipline_tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )

    # Relationships
    collect_tasks: Mapped[list["CollectTask"]] = relationship(back_populates="source")
    raw_contents: Mapped[list["RawContent"]] = relationship(back_populates="source")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="source")

    __table_args__ = (
        Index("ix_sources_status", "status"),
        Index("ix_sources_next_collect_at", "next_collect_at"),
        Index("ix_sources_tags", "tags", postgresql_using="gin"),
    )


# ---------------------------------------------------------------------------
# E-008: TaskChain
# ---------------------------------------------------------------------------


class TaskChain(ExecutionTimingMixin, CreatedAtMixin, Base):
    __tablename__ = "task_chains"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pipeline_name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, default="pending")
    trigger_type: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    execution_mode: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[Optional[str]] = mapped_column(VARCHAR(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    collect_tasks: Mapped[list["CollectTask"]] = relationship(
        back_populates="task_chain"
    )

    __table_args__ = (
        Index("ix_task_chains_status", "status"),
        Index("ix_task_chains_pipeline_name", "pipeline_name"),
    )


# ---------------------------------------------------------------------------
# E-002: CollectTask
# ---------------------------------------------------------------------------


class CollectTask(ExecutionTimingMixin, CreatedAtMixin, Base):
    __tablename__ = "collect_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False
    )
    task_chain_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_chains.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, default="pending")
    priority: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, default="normal")
    trigger_type: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    items_collected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    celery_task_id: Mapped[Optional[str]] = mapped_column(VARCHAR(64), nullable=True)

    # Relationships
    source: Mapped["Source"] = relationship(back_populates="collect_tasks")
    task_chain: Mapped[Optional["TaskChain"]] = relationship(
        back_populates="collect_tasks"
    )
    raw_contents: Mapped[list["RawContent"]] = relationship(
        back_populates="collect_task"
    )

    __table_args__ = (
        Index("ix_collect_tasks_status", "status"),
        Index("ix_collect_tasks_source_id", "source_id"),
        Index("ix_collect_tasks_task_chain_id", "task_chain_id"),
    )


# ---------------------------------------------------------------------------
# E-003: RawContent
# ---------------------------------------------------------------------------


class RawContent(CreatedAtMixin, Base):
    __tablename__ = "raw_contents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False
    )
    collect_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collect_tasks.id"), nullable=True
    )
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(VARCHAR(255), nullable=True)
    body_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    fingerprint: Mapped[str] = mapped_column(VARCHAR(64), nullable=False, unique=True)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, server_default="pending"
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Relationships
    source: Mapped["Source"] = relationship(back_populates="raw_contents")
    collect_task: Mapped[Optional["CollectTask"]] = relationship(
        back_populates="raw_contents"
    )
    processed_content: Mapped[Optional["ProcessedContent"]] = relationship(
        back_populates="raw_content", uselist=False
    )

    __table_args__ = (
        Index("ix_raw_contents_fingerprint", "fingerprint"),
        Index("ix_raw_contents_source_id", "source_id"),
        Index("ix_raw_contents_published_at", "published_at"),
    )


# ---------------------------------------------------------------------------
# E-005: ContentCluster
# ---------------------------------------------------------------------------


class ContentCluster(TimestampMixin, Base):
    __tablename__ = "content_clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    content_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    centroid = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, default="active")

    # Relationships
    processed_contents: Mapped[list["ProcessedContent"]] = relationship(
        back_populates="cluster"
    )
    digests: Mapped[list["Digest"]] = relationship(back_populates="cluster")

    __table_args__ = (
        Index("ix_content_clusters_tags", "tags", postgresql_using="gin"),
        Index("ix_content_clusters_updated_at", "updated_at"),
    )


# ---------------------------------------------------------------------------
# E-004: ProcessedContent
# ---------------------------------------------------------------------------


class ProcessedContent(CreatedAtMixin, Base):
    __tablename__ = "processed_contents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    raw_content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_contents.id"),
        nullable=False,
        unique=True,
    )
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    discipline_tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )
    cluster_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_clusters.id"), nullable=True
    )
    fingerprint: Mapped[Optional[str]] = mapped_column(VARCHAR(64), nullable=True)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    structured_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    processing_status: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, default="pending"
    )
    processed_by: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, default="llm"
    )
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_name: Mapped[Optional[str]] = mapped_column(VARCHAR(255), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Relationships
    raw_content: Mapped["RawContent"] = relationship(back_populates="processed_content")
    cluster: Mapped[Optional["ContentCluster"]] = relationship(
        back_populates="processed_contents"
    )

    __table_args__ = (
        Index("ix_processed_contents_processing_status", "processing_status"),
        Index("ix_processed_contents_cluster_id", "cluster_id"),
        Index("ix_processed_contents_tags", "tags", postgresql_using="gin"),
        Index(
            "ix_processed_contents_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_processed_contents_published_at", "published_at"),
        Index(
            "ix_processed_contents_fts",
            "body_text",
            postgresql_using="gin",
            postgresql_ops={"body_text": "gin_trgm_ops"},
        ),
    )


# ---------------------------------------------------------------------------
# E-006: Digest
# ---------------------------------------------------------------------------


class Digest(TimestampMixin, Base):
    __tablename__ = "digests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_clusters.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timeline: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    key_points: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    generated_by: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, default="llm"
    )

    # Relationships
    cluster: Mapped["ContentCluster"] = relationship(back_populates="digests")

    __table_args__ = (Index("ix_digests_cluster_id", "cluster_id"),)


# ---------------------------------------------------------------------------
# E-007: LLMCallLog
# ---------------------------------------------------------------------------


class LLMCallLog(CreatedAtMixin, Base):
    __tablename__ = "llm_call_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    provider: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    call_type: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    content_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processed_contents.id"),
        nullable=True,
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_length: Mapped[int] = mapped_column(Integer, nullable=False)
    output_length: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_attempt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_llm_call_logs_model", "model"),
        Index("ix_llm_call_logs_created_at", "created_at"),
        Index("ix_llm_call_logs_call_type", "call_type"),
        Index("ix_llm_call_logs_content_id", "content_id"),
    )


# ---------------------------------------------------------------------------
# E-009: Subscription
# ---------------------------------------------------------------------------


class Subscription(TimestampMixin, Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True
    )
    channel: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    channel_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    match_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    frequency: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, default="realtime"
    )
    quiet_hours: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    timezone: Mapped[str] = mapped_column(
        VARCHAR(100), nullable=False, default="Asia/Shanghai"
    )
    discipline_tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, default="active")
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Relationships
    source: Mapped[Optional["Source"]] = relationship(back_populates="subscriptions")
    push_records: Mapped[list["PushRecord"]] = relationship(
        back_populates="subscription"
    )

    __table_args__ = (
        Index("ix_subscriptions_channel", "channel"),
        Index("ix_subscriptions_status", "status"),
        Index(
            "ix_subscriptions_match_rules",
            "match_rules",
            postgresql_using="gin",
        ),
    )


# ---------------------------------------------------------------------------
# E-010: PushRecord
# ---------------------------------------------------------------------------


class PushRecord(CreatedAtMixin, Base):
    __tablename__ = "push_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=False
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processed_contents.id"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    recipient_id: Mapped[Optional[str]] = mapped_column(VARCHAR(255), nullable=True)
    render_mode: Mapped[Optional[str]] = mapped_column(VARCHAR(20), nullable=True)

    # Relationships
    subscription: Mapped["Subscription"] = relationship(back_populates="push_records")

    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "content_id",
            "channel",
            name="uq_push_records_dedup",
        ),
        Index("ix_push_records_subscription_id", "subscription_id"),
        Index("ix_push_records_content_id", "content_id"),
    )


# ---------------------------------------------------------------------------
# E-012: ChatSession
# ---------------------------------------------------------------------------


class ChatSession(CreatedAtMixin, Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    channel_user_id: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_chat_sessions_user", "channel", "channel_user_id"),
        Index("ix_chat_sessions_last_active_at", "last_active_at"),
    )


# ---------------------------------------------------------------------------
# E-013: Pipeline definition (header) + ordered steps
# ---------------------------------------------------------------------------


class Pipeline(TimestampMixin, Base):
    __tablename__ = "pipelines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False, unique=True)
    mode: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    on_failure: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, default="abort"
    )
    agent_mode: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, default="process"
    )
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_tokens_budget: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tools_allowed: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    tools_denied: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    tool_permissions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    steps: Mapped[list["PipelineStep"]] = relationship(
        back_populates="pipeline",
        cascade="all, delete-orphan",
        order_by="PipelineStep.position",
    )

    __table_args__ = (Index("ix_pipelines_status", "status"),)


class PipelineStep(CreatedAtMixin, Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    pipeline: Mapped["Pipeline"] = relationship(back_populates="steps")

    __table_args__ = (
        UniqueConstraint("pipeline_id", "position", name="uq_pipeline_steps_position"),
        Index("ix_pipeline_steps_pipeline_id", "pipeline_id"),
    )


class Template(TimestampMixin, Base):
    """A user-defined digest template: per-format Jinja source + a built-in base."""

    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(VARCHAR(255), nullable=False, unique=True)
    base_template: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    formats: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    default_format: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    jinja_source: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    aggregate_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, default="active")

    __table_args__ = (Index("ix_templates_status", "status"),)


class ConfigVersion(CreatedAtMixin, Base):
    """A persisted snapshot of the source-config set, keyed by version label."""

    __tablename__ = "config_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    version: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    snapshot_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_config_versions_version", "version", unique=True),)


class SubscriptionConfigVersion(CreatedAtMixin, Base):
    """A persisted snapshot of the subscription-config set, keyed by version."""

    __tablename__ = "subscription_config_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    version: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    snapshot_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_subscription_config_versions_version", "version", unique=True),
    )
