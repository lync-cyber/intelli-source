"""Tests for ORM model definitions (T-003).

Verifies all 11 entity models have correct column types, constraints,
foreign keys, defaults, indexes, and pgvector fields per arch spec.
"""

from __future__ import annotations

import pytest

from intellisource.storage.models import (
    ChatSession,
    CollectTask,
    ContentCluster,
    Digest,
    LLMCallLog,
    ProcessedContent,
    PushRecord,
    RawContent,
    Source,
    Subscription,
    TaskChain,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _col(model, name):
    """Return a SQLAlchemy Column object from a model's __table__."""
    return model.__table__.columns[name]


def _col_type_name(model, name):
    """Return upper-cased string of column type (e.g. 'VARCHAR', 'UUID')."""
    return type(_col(model, name).type).__name__.upper()


def _has_fk_to(model, col_name, target_table):
    """Check if column has a FK referencing target_table."""
    col = _col(model, col_name)
    return any(fk.column.table.name == target_table for fk in col.foreign_keys)


# ===========================================================================
# AC-T003-1: Field types and definitions for all 11 models
# ===========================================================================


class TestSourceModel:
    """E-001 Source entity."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID", "nullable": False, "primary_key": True},
        "name": {"type": "VARCHAR", "nullable": False},
        "type": {"type": "VARCHAR", "nullable": False},
        "url": {"type": "TEXT", "nullable": False},
        "tags": {"type": "JSONB", "nullable": True},
        "status": {"type": "VARCHAR", "nullable": True},
        "schedule_interval": {"type": "INTEGER", "nullable": True},
        "schedule_adaptive": {"type": "BOOLEAN", "nullable": True},
        "proxy": {"type": "VARCHAR", "nullable": True},
        "rate_limit_qps": {"type": "NUMERIC", "nullable": True},
        "rate_limit_concurrency": {"type": "INTEGER", "nullable": True},
        "metadata": {"type": "JSONB", "nullable": True},
        "last_collected_at": {"type": "TIMESTAMP", "nullable": True},
        "next_collect_at": {"type": "TIMESTAMP", "nullable": True},
        "error_count": {"type": "INTEGER", "nullable": True},
        "avg_update_interval": {"type": "INTEGER", "nullable": True},
        "http_etag": {"type": "VARCHAR", "nullable": True},
        "http_last_modified": {"type": "VARCHAR", "nullable": True},
        "config_version": {"type": "INTEGER", "nullable": True},
        "created_at": {"type": "TIMESTAMP", "nullable": True},
        "updated_at": {"type": "TIMESTAMP", "nullable": True},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in Source.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(Source, col_name)
        assert expected["type"] in actual_type

    def test_name_unique(self):
        col = _col(Source, "name")
        assert col.unique is True

    def test_table_name(self):
        assert Source.__tablename__ == "sources"


class TestTaskChainModel:
    """E-008 TaskChain (defined before CollectTask due to FK dependency)."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID"},
        "pipeline_name": {"type": "VARCHAR"},
        "status": {"type": "VARCHAR"},
        "trigger_type": {"type": "VARCHAR"},
        "execution_mode": {"type": "VARCHAR"},
        "total_steps": {"type": "INTEGER"},
        "completed_steps": {"type": "INTEGER"},
        "current_step": {"type": "VARCHAR"},
        "error_message": {"type": "TEXT"},
        "started_at": {"type": "TIMESTAMP"},
        "finished_at": {"type": "TIMESTAMP"},
        "created_at": {"type": "TIMESTAMP"},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in TaskChain.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(TaskChain, col_name)
        assert expected["type"] in actual_type

    def test_table_name(self):
        assert TaskChain.__tablename__ == "task_chains"


class TestCollectTaskModel:
    """E-002 CollectTask entity."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID"},
        "source_id": {"type": "UUID"},
        "task_chain_id": {"type": "UUID"},
        "status": {"type": "VARCHAR"},
        "priority": {"type": "VARCHAR"},
        "trigger_type": {"type": "VARCHAR"},
        "items_collected": {"type": "INTEGER"},
        "error_message": {"type": "TEXT"},
        "retry_count": {"type": "INTEGER"},
        "started_at": {"type": "TIMESTAMP"},
        "finished_at": {"type": "TIMESTAMP"},
        "created_at": {"type": "TIMESTAMP"},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in CollectTask.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(CollectTask, col_name)
        assert expected["type"] in actual_type

    def test_table_name(self):
        assert CollectTask.__tablename__ == "collect_tasks"


class TestRawContentModel:
    """E-003 RawContent entity."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID"},
        "source_id": {"type": "UUID"},
        "collect_task_id": {"type": "UUID"},
        "title": {"type": "TEXT"},
        "author": {"type": "VARCHAR"},
        "body_html": {"type": "TEXT"},
        "body_text": {"type": "TEXT"},
        "source_url": {"type": "TEXT"},
        "published_at": {"type": "TIMESTAMP"},
        "fingerprint": {"type": "VARCHAR"},
        "raw_metadata": {"type": "JSONB"},
        "created_at": {"type": "TIMESTAMP"},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in RawContent.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(RawContent, col_name)
        assert expected["type"] in actual_type

    def test_fingerprint_unique(self):
        col = _col(RawContent, "fingerprint")
        assert col.unique is True

    def test_table_name(self):
        assert RawContent.__tablename__ == "raw_contents"


class TestProcessedContentModel:
    """E-004 ProcessedContent entity."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID"},
        "raw_content_id": {"type": "UUID"},
        "title": {"type": "TEXT"},
        "body_text": {"type": "TEXT"},
        "summary": {"type": "TEXT"},
        "tags": {"type": "JSONB"},
        "cluster_id": {"type": "UUID"},
        "fingerprint": {"type": "VARCHAR"},
        "embedding": {"type": "VECTOR"},
        "structured_data": {"type": "JSONB"},
        "processing_status": {"type": "VARCHAR"},
        "processed_by": {"type": "VARCHAR"},
        "source_url": {"type": "TEXT"},
        "source_name": {"type": "VARCHAR"},
        "published_at": {"type": "TIMESTAMP"},
        "processed_at": {"type": "TIMESTAMP"},
        "created_at": {"type": "TIMESTAMP"},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in ProcessedContent.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(ProcessedContent, col_name)
        assert expected["type"] in actual_type

    def test_raw_content_id_unique(self):
        col = _col(ProcessedContent, "raw_content_id")
        assert col.unique is True

    def test_table_name(self):
        assert ProcessedContent.__tablename__ == "processed_contents"


class TestContentClusterModel:
    """E-005 ContentCluster entity."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID"},
        "topic": {"type": "TEXT"},
        "tags": {"type": "JSONB"},
        "content_count": {"type": "INTEGER"},
        "centroid": {"type": "VECTOR"},
        "status": {"type": "VARCHAR"},
        "created_at": {"type": "TIMESTAMP"},
        "updated_at": {"type": "TIMESTAMP"},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in ContentCluster.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(ContentCluster, col_name)
        assert expected["type"] in actual_type

    def test_table_name(self):
        assert ContentCluster.__tablename__ == "content_clusters"


class TestDigestModel:
    """E-006 Digest entity."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID"},
        "cluster_id": {"type": "UUID"},
        "title": {"type": "TEXT"},
        "summary": {"type": "TEXT"},
        "timeline": {"type": "JSONB"},
        "key_points": {"type": "JSONB"},
        "generated_by": {"type": "VARCHAR"},
        "created_at": {"type": "TIMESTAMP"},
        "updated_at": {"type": "TIMESTAMP"},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in Digest.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(Digest, col_name)
        assert expected["type"] in actual_type

    def test_table_name(self):
        assert Digest.__tablename__ == "digests"


class TestLLMCallLogModel:
    """E-007 LLMCallLog entity."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID"},
        "model": {"type": "VARCHAR"},
        "provider": {"type": "VARCHAR"},
        "call_type": {"type": "VARCHAR"},
        "content_id": {"type": "UUID"},
        "input_tokens": {"type": "INTEGER"},
        "output_tokens": {"type": "INTEGER"},
        "latency_ms": {"type": "INTEGER"},
        "input_length": {"type": "INTEGER"},
        "output_length": {"type": "INTEGER"},
        "status": {"type": "VARCHAR"},
        "error_message": {"type": "TEXT"},
        "created_at": {"type": "TIMESTAMP"},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in LLMCallLog.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(LLMCallLog, col_name)
        assert expected["type"] in actual_type

    def test_table_name(self):
        assert LLMCallLog.__tablename__ == "llm_call_logs"


class TestSubscriptionModel:
    """E-009 Subscription entity."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID"},
        "name": {"type": "VARCHAR"},
        "source_id": {"type": "UUID"},
        "channel": {"type": "VARCHAR"},
        "channel_config": {"type": "JSONB"},
        "match_rules": {"type": "JSONB"},
        "frequency": {"type": "VARCHAR"},
        "quiet_hours": {"type": "JSONB"},
        "status": {"type": "VARCHAR"},
        "last_sent_at": {"type": "TIMESTAMP"},
        "created_at": {"type": "TIMESTAMP"},
        "updated_at": {"type": "TIMESTAMP"},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in Subscription.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(Subscription, col_name)
        assert expected["type"] in actual_type

    def test_table_name(self):
        assert Subscription.__tablename__ == "subscriptions"

    def test_last_sent_at_nullable(self):
        """Periodic-digest watermark starts empty (never sent)."""
        assert _col(Subscription, "last_sent_at").nullable is True


class TestPushRecordModel:
    """E-010 PushRecord entity."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID"},
        "subscription_id": {"type": "UUID"},
        "content_id": {"type": "UUID"},
        "channel": {"type": "VARCHAR"},
        "status": {"type": "VARCHAR"},
        "retry_count": {"type": "INTEGER"},
        "error_message": {"type": "TEXT"},
        "sent_at": {"type": "TIMESTAMP"},
        "delivered_at": {"type": "TIMESTAMP"},
        "created_at": {"type": "TIMESTAMP"},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in PushRecord.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(PushRecord, col_name)
        assert expected["type"] in actual_type

    def test_unique_constraint_subscription_content_channel(self):
        """Unique constraint on (subscription_id, content_id, channel)."""
        from sqlalchemy import UniqueConstraint

        table = PushRecord.__table__
        found = False
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                cols = {c.name for c in constraint.columns}
                if cols == {"subscription_id", "content_id", "channel"}:
                    found = True
                    break
        assert found, (
            "Missing unique constraint on (subscription_id, content_id, channel)"
        )

    def test_table_name(self):
        assert PushRecord.__tablename__ == "push_records"


class TestChatSessionModel:
    """E-011 ChatSession entity."""

    EXPECTED_COLUMNS = {
        "id": {"type": "UUID"},
        "channel": {"type": "VARCHAR"},
        "channel_user_id": {"type": "VARCHAR"},
        "context": {"type": "JSONB"},
        "last_active_at": {"type": "TIMESTAMP"},
        "created_at": {"type": "TIMESTAMP"},
    }

    @pytest.mark.parametrize("col_name", EXPECTED_COLUMNS.keys())
    def test_column_exists(self, col_name):
        assert col_name in ChatSession.__table__.columns

    @pytest.mark.parametrize(
        "col_name,expected",
        [(k, v) for k, v in EXPECTED_COLUMNS.items()],
        ids=EXPECTED_COLUMNS.keys(),
    )
    def test_column_type(self, col_name, expected):
        actual_type = _col_type_name(ChatSession, col_name)
        assert expected["type"] in actual_type

    def test_table_name(self):
        assert ChatSession.__tablename__ == "chat_sessions"


# ===========================================================================
# AC-T003-2: Foreign key relationships
# ===========================================================================


class TestForeignKeys:
    """Verify FK references across all models."""

    @pytest.mark.parametrize(
        "model,col_name,target_table",
        [
            (CollectTask, "source_id", "sources"),
            (CollectTask, "task_chain_id", "task_chains"),
            (RawContent, "source_id", "sources"),
            (RawContent, "collect_task_id", "collect_tasks"),
            (ProcessedContent, "raw_content_id", "raw_contents"),
            (ProcessedContent, "cluster_id", "content_clusters"),
            (Digest, "cluster_id", "content_clusters"),
            (Subscription, "source_id", "sources"),
            (PushRecord, "subscription_id", "subscriptions"),
            (PushRecord, "content_id", "processed_contents"),
        ],
        ids=[
            "CollectTask.source_id->sources",
            "CollectTask.task_chain_id->task_chains",
            "RawContent.source_id->sources",
            "RawContent.collect_task_id->collect_tasks",
            "ProcessedContent.raw_content_id->raw_contents",
            "ProcessedContent.cluster_id->content_clusters",
            "Digest.cluster_id->content_clusters",
            "Subscription.source_id->sources",
            "PushRecord.subscription_id->subscriptions",
            "PushRecord.content_id->processed_contents",
        ],
    )
    def test_fk_target(self, model, col_name, target_table):
        assert _has_fk_to(model, col_name, target_table)


# ===========================================================================
# AC-T003-3: JSONB field defaults
# ===========================================================================


class TestJSONBDefaults:
    """Verify JSONB columns have correct server/Python defaults."""

    @pytest.mark.parametrize(
        "model,col_name,expected_default",
        [
            (Source, "tags", []),
            (Source, "metadata", {}),
            (RawContent, "raw_metadata", {}),
            (ProcessedContent, "tags", []),
            (ContentCluster, "tags", []),
            (Digest, "key_points", []),
            (ChatSession, "context", {}),
        ],
        ids=[
            "Source.tags=[]",
            "Source.metadata={}",
            "RawContent.raw_metadata={}",
            "ProcessedContent.tags=[]",
            "ContentCluster.tags=[]",
            "Digest.key_points=[]",
            "ChatSession.context={}",
        ],
    )
    def test_jsonb_default(self, model, col_name, expected_default):
        col = _col(model, col_name)
        default = col.default
        if default is not None and hasattr(default, "arg"):
            if callable(default.arg):
                assert default.arg(None) == expected_default
            else:
                assert default.arg == expected_default
        elif col.server_default is not None:
            text = str(col.server_default.arg)
            if expected_default == []:
                assert "'[]'" in text or "[]" in text
            else:
                assert "'{}'" in text or "{}" in text
        else:
            pytest.fail(f"{model.__name__}.{col_name} has no default for JSONB")


# ===========================================================================
# AC-T003-4: pgvector VECTOR(1536) field definition
# ===========================================================================


class TestVectorFields:
    """Verify pgvector VECTOR(1536) columns."""

    @pytest.mark.parametrize(
        "model,col_name",
        [
            (ProcessedContent, "embedding"),
            (ContentCluster, "centroid"),
        ],
        ids=["ProcessedContent.embedding", "ContentCluster.centroid"],
    )
    def test_vector_column_type(self, model, col_name):
        col = _col(model, col_name)
        type_name = type(col.type).__name__.upper()
        assert "VECTOR" in type_name

    @pytest.mark.parametrize(
        "model,col_name",
        [
            (ProcessedContent, "embedding"),
            (ContentCluster, "centroid"),
        ],
        ids=["ProcessedContent.embedding_dim", "ContentCluster.centroid_dim"],
    )
    def test_vector_dimension_1536(self, model, col_name):
        col = _col(model, col_name)
        dim = getattr(col.type, "dim", None)
        assert dim == 1536, f"Expected dim=1536, got {dim}"


# ===========================================================================
# AC-T003-5: Index declarations
# ===========================================================================


class TestIndexes:
    """Verify key indexes are declared on models."""

    @pytest.mark.parametrize(
        "model,index_columns",
        [
            (Source, ("status",)),
            (CollectTask, ("source_id",)),
            (CollectTask, ("status",)),
            (RawContent, ("fingerprint",)),
            (RawContent, ("source_id",)),
            (ProcessedContent, ("processing_status",)),
            (ProcessedContent, ("cluster_id",)),
            (LLMCallLog, ("created_at",)),
            (LLMCallLog, ("content_id",)),
            (PushRecord, ("subscription_id",)),
        ],
        ids=[
            "Source.ix_status",
            "CollectTask.ix_source_id",
            "CollectTask.ix_status",
            "RawContent.ix_fingerprint",
            "RawContent.ix_source_id",
            "ProcessedContent.ix_processing_status",
            "ProcessedContent.ix_cluster_id",
            "LLMCallLog.ix_created_at",
            "LLMCallLog.ix_content_id",
            "PushRecord.ix_subscription_id",
        ],
    )
    def test_index_exists(self, model, index_columns):
        table = model.__table__
        indexed_col_sets = [tuple(c.name for c in idx.columns) for idx in table.indexes]
        assert index_columns in indexed_col_sets, (
            f"Expected index on {index_columns} in {model.__name__}, "
            f"found indexes on: {indexed_col_sets}"
        )


# ===========================================================================
# AC-T003-6: Alembic migration (skipped per task spec)
# ===========================================================================

# TODO: Alembic migration tests to be added when Alembic infrastructure is set up.
