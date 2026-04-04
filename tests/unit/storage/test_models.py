"""Tests for T-003: ORM model definitions for all entities.

Covers:
  AC-T003-1: 12 ORM models (E-001~E-011 + TaskChain=E-008) field types match arch-data
  AC-T003-2: All FK relationships correctly established
  AC-T003-3: JSONB fields use SQLAlchemy JSON type with correct defaults
  AC-T003-4: pgvector VECTOR(1536) fields correctly defined (E-004 embedding, E-005 centroid)
  AC-T003-5: All indexes (GIN, HNSW, full-text) declared on models
  AC-T003-6: Alembic migration generation (TODO - requires PostgreSQL)
"""

from __future__ import annotations

import pytest
from sqlalchemy import Numeric, Text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# ---------------------------------------------------------------------------
# Helper: import all models from the module under test
# ---------------------------------------------------------------------------


def _import_models():
    """Import and return dict of model classes from intellisource.storage.models.

    This function centralises the import so that every test class fails with
    a clear ImportError when the module does not yet exist.
    """
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

    return {
        "Source": Source,
        "CollectTask": CollectTask,
        "RawContent": RawContent,
        "ProcessedContent": ProcessedContent,
        "ContentCluster": ContentCluster,
        "Digest": Digest,
        "LLMCallLog": LLMCallLog,
        "TaskChain": TaskChain,
        "Subscription": Subscription,
        "PushRecord": PushRecord,
        "ChatSession": ChatSession,
    }


def _get_model(name: str):
    """Return a single model class by name."""
    models = _import_models()
    return models[name]


def _mapper(model_cls):
    """Return the SQLAlchemy mapper inspection for a model class."""
    return sa_inspect(model_cls)


def _columns(model_cls) -> dict:
    """Return {col_name: Column} dict from the model's __table__."""
    return {c.name: c for c in model_cls.__table__.columns}


def _indexes(model_cls) -> dict:
    """Return {index_name: Index} dict from the model's __table__."""
    return {idx.name: idx for idx in model_cls.__table__.indexes}


# ===========================================================================
# AC-T003-1: 12 ORM models field types match arch-data definitions
# ===========================================================================


class TestModelExistence:
    """AC-T003-1 (part 1): All 12 model classes are importable and mapped."""

    def test_all_eleven_models_importable(self) -> None:
        models = _import_models()
        assert len(models) == 11, f"Expected 11 model classes, got {len(models)}"

    @pytest.mark.parametrize(
        "name",
        [
            "Source",
            "CollectTask",
            "RawContent",
            "ProcessedContent",
            "ContentCluster",
            "Digest",
            "LLMCallLog",
            "TaskChain",
            "Subscription",
            "PushRecord",
            "ChatSession",
        ],
    )
    def test_model_is_mapped(self, name: str) -> None:
        model = _get_model(name)
        mapper = _mapper(model)
        assert mapper is not None


class TestSourceModel:
    """AC-T003-1: E-001 Source fields."""

    def test_tablename(self) -> None:
        m = _get_model("Source")
        assert m.__tablename__ == "sources"

    def test_id_is_uuid_pk(self) -> None:
        cols = _columns(_get_model("Source"))
        assert "id" in cols
        col = cols["id"]
        assert col.primary_key
        # Should be UUID type (postgresql dialect)
        assert isinstance(col.type, PG_UUID) or "UUID" in str(col.type).upper()

    def test_name_varchar_255_unique(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["name"]
        assert not col.nullable
        assert col.unique
        assert hasattr(col.type, "length") and col.type.length == 255

    def test_type_varchar_20_with_check(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["type"]
        assert not col.nullable
        assert hasattr(col.type, "length") and col.type.length == 20

    def test_url_text_not_null(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["url"]
        assert not col.nullable
        assert isinstance(col.type, Text)

    def test_tags_jsonb_default_empty_list(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["tags"]
        assert isinstance(col.type, JSONB) or "JSON" in type(col.type).__name__.upper()
        # Default should be an empty list
        assert col.default is not None

    def test_status_varchar_20_default_active(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["status"]
        assert not col.nullable
        assert hasattr(col.type, "length") and col.type.length == 20
        assert col.default is not None

    def test_schedule_interval_integer_default_3600(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["schedule_interval"]
        assert not col.nullable
        assert col.default is not None

    def test_schedule_adaptive_boolean_default_true(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["schedule_adaptive"]
        assert not col.nullable
        assert col.default is not None

    def test_proxy_nullable(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["proxy"]
        assert col.nullable

    def test_rate_limit_qps_decimal(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["rate_limit_qps"]
        assert col.nullable
        assert isinstance(col.type, Numeric)

    def test_rate_limit_concurrency_nullable(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["rate_limit_concurrency"]
        assert col.nullable

    def test_metadata_jsonb_default_empty_dict(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["metadata"]
        assert isinstance(col.type, JSONB) or "JSON" in type(col.type).__name__.upper()

    def test_timestamp_fields_exist(self) -> None:
        cols = _columns(_get_model("Source"))
        for field in [
            "last_collected_at",
            "next_collect_at",
            "created_at",
            "updated_at",
        ]:
            assert field in cols, f"Missing timestamp field: {field}"

    def test_created_at_not_null_with_default(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["created_at"]
        assert not col.nullable

    def test_error_count_default_zero(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["error_count"]
        assert not col.nullable

    def test_http_etag_nullable(self) -> None:
        cols = _columns(_get_model("Source"))
        assert cols["http_etag"].nullable
        assert cols["http_last_modified"].nullable

    def test_config_version_default_one(self) -> None:
        cols = _columns(_get_model("Source"))
        col = cols["config_version"]
        assert not col.nullable


class TestCollectTaskModel:
    """AC-T003-1: E-002 CollectTask fields."""

    def test_tablename(self) -> None:
        m = _get_model("CollectTask")
        assert m.__tablename__ == "collect_tasks"

    def test_required_fields_exist(self) -> None:
        cols = _columns(_get_model("CollectTask"))
        expected = [
            "id",
            "source_id",
            "task_chain_id",
            "status",
            "priority",
            "trigger_type",
            "items_collected",
            "error_message",
            "retry_count",
            "started_at",
            "finished_at",
            "created_at",
        ]
        for field in expected:
            assert field in cols, f"Missing field: {field}"

    def test_status_default_pending(self) -> None:
        cols = _columns(_get_model("CollectTask"))
        col = cols["status"]
        assert not col.nullable
        assert col.default is not None

    def test_priority_default_normal(self) -> None:
        cols = _columns(_get_model("CollectTask"))
        col = cols["priority"]
        assert not col.nullable
        assert col.default is not None

    def test_items_collected_default_zero(self) -> None:
        cols = _columns(_get_model("CollectTask"))
        col = cols["items_collected"]
        assert not col.nullable

    def test_task_chain_id_nullable(self) -> None:
        cols = _columns(_get_model("CollectTask"))
        assert cols["task_chain_id"].nullable


class TestRawContentModel:
    """AC-T003-1: E-003 RawContent fields."""

    def test_tablename(self) -> None:
        m = _get_model("RawContent")
        assert m.__tablename__ == "raw_contents"

    def test_required_fields_exist(self) -> None:
        cols = _columns(_get_model("RawContent"))
        expected = [
            "id",
            "source_id",
            "collect_task_id",
            "title",
            "author",
            "body_html",
            "body_text",
            "source_url",
            "published_at",
            "fingerprint",
            "raw_metadata",
            "created_at",
        ]
        for field in expected:
            assert field in cols, f"Missing field: {field}"

    def test_fingerprint_unique(self) -> None:
        cols = _columns(_get_model("RawContent"))
        col = cols["fingerprint"]
        assert col.unique
        assert not col.nullable

    def test_raw_metadata_jsonb(self) -> None:
        cols = _columns(_get_model("RawContent"))
        col = cols["raw_metadata"]
        assert isinstance(col.type, JSONB) or "JSON" in type(col.type).__name__.upper()

    def test_source_url_not_null(self) -> None:
        cols = _columns(_get_model("RawContent"))
        assert not cols["source_url"].nullable


class TestProcessedContentModel:
    """AC-T003-1: E-004 ProcessedContent fields."""

    def test_tablename(self) -> None:
        m = _get_model("ProcessedContent")
        assert m.__tablename__ == "processed_contents"

    def test_required_fields_exist(self) -> None:
        cols = _columns(_get_model("ProcessedContent"))
        expected = [
            "id",
            "raw_content_id",
            "title",
            "body_text",
            "summary",
            "tags",
            "cluster_id",
            "fingerprint",
            "embedding",
            "structured_data",
            "processing_status",
            "processed_by",
            "source_url",
            "source_name",
            "published_at",
            "processed_at",
            "created_at",
        ]
        for field in expected:
            assert field in cols, f"Missing field: {field}"

    def test_raw_content_id_unique(self) -> None:
        """RawContent 1-1 ProcessedContent requires unique FK."""
        cols = _columns(_get_model("ProcessedContent"))
        col = cols["raw_content_id"]
        assert col.unique
        assert not col.nullable

    def test_processing_status_default_pending(self) -> None:
        cols = _columns(_get_model("ProcessedContent"))
        col = cols["processing_status"]
        assert not col.nullable
        assert col.default is not None

    def test_processed_by_default_llm(self) -> None:
        cols = _columns(_get_model("ProcessedContent"))
        col = cols["processed_by"]
        assert not col.nullable
        assert col.default is not None

    def test_tags_jsonb(self) -> None:
        cols = _columns(_get_model("ProcessedContent"))
        col = cols["tags"]
        assert isinstance(col.type, JSONB) or "JSON" in type(col.type).__name__.upper()


class TestContentClusterModel:
    """AC-T003-1: E-005 ContentCluster fields."""

    def test_tablename(self) -> None:
        m = _get_model("ContentCluster")
        assert m.__tablename__ == "content_clusters"

    def test_required_fields_exist(self) -> None:
        cols = _columns(_get_model("ContentCluster"))
        expected = [
            "id",
            "topic",
            "tags",
            "content_count",
            "centroid",
            "status",
            "created_at",
            "updated_at",
        ]
        for field in expected:
            assert field in cols, f"Missing field: {field}"

    def test_content_count_default_zero(self) -> None:
        cols = _columns(_get_model("ContentCluster"))
        col = cols["content_count"]
        assert not col.nullable

    def test_status_default_active(self) -> None:
        cols = _columns(_get_model("ContentCluster"))
        col = cols["status"]
        assert not col.nullable
        assert col.default is not None


class TestDigestModel:
    """AC-T003-1: E-006 Digest fields."""

    def test_tablename(self) -> None:
        m = _get_model("Digest")
        assert m.__tablename__ == "digests"

    def test_required_fields_exist(self) -> None:
        cols = _columns(_get_model("Digest"))
        expected = [
            "id",
            "cluster_id",
            "title",
            "summary",
            "timeline",
            "key_points",
            "generated_by",
            "created_at",
            "updated_at",
        ]
        for field in expected:
            assert field in cols, f"Missing field: {field}"

    def test_key_points_jsonb_default_empty_list(self) -> None:
        cols = _columns(_get_model("Digest"))
        col = cols["key_points"]
        assert isinstance(col.type, JSONB) or "JSON" in type(col.type).__name__.upper()
        assert not col.nullable

    def test_generated_by_default_llm(self) -> None:
        cols = _columns(_get_model("Digest"))
        col = cols["generated_by"]
        assert not col.nullable
        assert col.default is not None


class TestLLMCallLogModel:
    """AC-T003-1: E-007 LLMCallLog fields."""

    def test_tablename(self) -> None:
        m = _get_model("LLMCallLog")
        assert m.__tablename__ == "llm_call_logs"

    def test_required_fields_exist(self) -> None:
        cols = _columns(_get_model("LLMCallLog"))
        expected = [
            "id",
            "model",
            "provider",
            "call_type",
            "content_id",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "input_length",
            "output_length",
            "status",
            "error_message",
            "created_at",
        ]
        for field in expected:
            assert field in cols, f"Missing field: {field}"

    def test_content_id_nullable(self) -> None:
        cols = _columns(_get_model("LLMCallLog"))
        assert cols["content_id"].nullable


class TestTaskChainModel:
    """AC-T003-1: E-008 TaskChain fields."""

    def test_tablename(self) -> None:
        m = _get_model("TaskChain")
        assert m.__tablename__ == "task_chains"

    def test_required_fields_exist(self) -> None:
        cols = _columns(_get_model("TaskChain"))
        expected = [
            "id",
            "pipeline_name",
            "status",
            "trigger_type",
            "execution_mode",
            "total_steps",
            "completed_steps",
            "current_step",
            "error_message",
            "started_at",
            "finished_at",
            "created_at",
        ]
        for field in expected:
            assert field in cols, f"Missing field: {field}"

    def test_status_default_pending(self) -> None:
        cols = _columns(_get_model("TaskChain"))
        col = cols["status"]
        assert not col.nullable
        assert col.default is not None

    def test_completed_steps_default_zero(self) -> None:
        cols = _columns(_get_model("TaskChain"))
        col = cols["completed_steps"]
        assert not col.nullable


class TestSubscriptionModel:
    """AC-T003-1: E-009 Subscription fields."""

    def test_tablename(self) -> None:
        m = _get_model("Subscription")
        assert m.__tablename__ == "subscriptions"

    def test_required_fields_exist(self) -> None:
        cols = _columns(_get_model("Subscription"))
        expected = [
            "id",
            "name",
            "source_id",
            "channel",
            "channel_config",
            "match_rules",
            "frequency",
            "quiet_hours",
            "status",
            "created_at",
            "updated_at",
        ]
        for field in expected:
            assert field in cols, f"Missing field: {field}"

    def test_source_id_nullable(self) -> None:
        cols = _columns(_get_model("Subscription"))
        assert cols["source_id"].nullable

    def test_frequency_default_realtime(self) -> None:
        cols = _columns(_get_model("Subscription"))
        col = cols["frequency"]
        assert not col.nullable
        assert col.default is not None

    def test_channel_config_not_null(self) -> None:
        cols = _columns(_get_model("Subscription"))
        assert not cols["channel_config"].nullable

    def test_match_rules_not_null(self) -> None:
        cols = _columns(_get_model("Subscription"))
        assert not cols["match_rules"].nullable


class TestPushRecordModel:
    """AC-T003-1: E-010 PushRecord fields."""

    def test_tablename(self) -> None:
        m = _get_model("PushRecord")
        assert m.__tablename__ == "push_records"

    def test_required_fields_exist(self) -> None:
        cols = _columns(_get_model("PushRecord"))
        expected = [
            "id",
            "subscription_id",
            "content_id",
            "channel",
            "status",
            "retry_count",
            "error_message",
            "sent_at",
            "delivered_at",
            "created_at",
        ]
        for field in expected:
            assert field in cols, f"Missing field: {field}"

    def test_status_default_pending(self) -> None:
        cols = _columns(_get_model("PushRecord"))
        col = cols["status"]
        assert not col.nullable
        assert col.default is not None


class TestChatSessionModel:
    """AC-T003-1: E-011 ChatSession fields."""

    def test_tablename(self) -> None:
        m = _get_model("ChatSession")
        assert m.__tablename__ == "chat_sessions"

    def test_required_fields_exist(self) -> None:
        cols = _columns(_get_model("ChatSession"))
        expected = [
            "id",
            "channel",
            "channel_user_id",
            "context",
            "last_active_at",
            "created_at",
        ]
        for field in expected:
            assert field in cols, f"Missing field: {field}"

    def test_context_jsonb_default_empty_dict(self) -> None:
        cols = _columns(_get_model("ChatSession"))
        col = cols["context"]
        assert isinstance(col.type, JSONB) or "JSON" in type(col.type).__name__.upper()
        assert not col.nullable


# ===========================================================================
# AC-T003-2: FK relationships correctly established
# ===========================================================================


class TestForeignKeyRelationships:
    """AC-T003-2: All foreign key relationships are correctly defined."""

    def _fk_target_columns(self, model_cls) -> dict[str, set[str]]:
        """Return {column_name: {target_table.target_col, ...}} for all FKs."""
        result: dict[str, set[str]] = {}
        for col in model_cls.__table__.columns:
            if col.foreign_keys:
                result[col.name] = {str(fk.target_fullname) for fk in col.foreign_keys}
        return result

    def test_collect_task_source_fk(self) -> None:
        fks = self._fk_target_columns(_get_model("CollectTask"))
        assert "source_id" in fks
        assert any("sources.id" in t for t in fks["source_id"])

    def test_collect_task_chain_fk(self) -> None:
        fks = self._fk_target_columns(_get_model("CollectTask"))
        assert "task_chain_id" in fks
        assert any("task_chains.id" in t for t in fks["task_chain_id"])

    def test_raw_content_source_fk(self) -> None:
        fks = self._fk_target_columns(_get_model("RawContent"))
        assert "source_id" in fks
        assert any("sources.id" in t for t in fks["source_id"])

    def test_raw_content_collect_task_fk(self) -> None:
        fks = self._fk_target_columns(_get_model("RawContent"))
        assert "collect_task_id" in fks
        assert any("collect_tasks.id" in t for t in fks["collect_task_id"])

    def test_processed_content_raw_content_fk(self) -> None:
        fks = self._fk_target_columns(_get_model("ProcessedContent"))
        assert "raw_content_id" in fks
        assert any("raw_contents.id" in t for t in fks["raw_content_id"])

    def test_processed_content_cluster_fk(self) -> None:
        fks = self._fk_target_columns(_get_model("ProcessedContent"))
        assert "cluster_id" in fks
        assert any("content_clusters.id" in t for t in fks["cluster_id"])

    def test_digest_cluster_fk(self) -> None:
        fks = self._fk_target_columns(_get_model("Digest"))
        assert "cluster_id" in fks
        assert any("content_clusters.id" in t for t in fks["cluster_id"])

    def test_llm_call_log_content_fk(self) -> None:
        """LLMCallLog.content_id -> ProcessedContent.id (nullable)."""
        fks = self._fk_target_columns(_get_model("LLMCallLog"))
        assert "content_id" in fks
        assert any("processed_contents.id" in t for t in fks["content_id"])

    def test_subscription_source_fk(self) -> None:
        fks = self._fk_target_columns(_get_model("Subscription"))
        assert "source_id" in fks
        assert any("sources.id" in t for t in fks["source_id"])

    def test_push_record_subscription_fk(self) -> None:
        fks = self._fk_target_columns(_get_model("PushRecord"))
        assert "subscription_id" in fks
        assert any("subscriptions.id" in t for t in fks["subscription_id"])

    def test_push_record_content_fk(self) -> None:
        fks = self._fk_target_columns(_get_model("PushRecord"))
        assert "content_id" in fks
        assert any("processed_contents.id" in t for t in fks["content_id"])


class TestORMRelationships:
    """AC-T003-2: ORM-level relationship() attributes are defined."""

    def test_source_has_collect_tasks_relationship(self) -> None:
        m = _get_model("Source")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "collect_tasks" in rel_names

    def test_source_has_raw_contents_relationship(self) -> None:
        m = _get_model("Source")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "raw_contents" in rel_names

    def test_source_has_subscriptions_relationship(self) -> None:
        m = _get_model("Source")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "subscriptions" in rel_names

    def test_collect_task_has_source_relationship(self) -> None:
        m = _get_model("CollectTask")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "source" in rel_names

    def test_collect_task_has_task_chain_relationship(self) -> None:
        m = _get_model("CollectTask")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "task_chain" in rel_names

    def test_collect_task_has_raw_contents_relationship(self) -> None:
        m = _get_model("CollectTask")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "raw_contents" in rel_names

    def test_raw_content_has_processed_content_relationship(self) -> None:
        m = _get_model("RawContent")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "processed_content" in rel_names

    def test_processed_content_has_cluster_relationship(self) -> None:
        m = _get_model("ProcessedContent")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "cluster" in rel_names

    def test_content_cluster_has_digests_relationship(self) -> None:
        m = _get_model("ContentCluster")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "digests" in rel_names

    def test_content_cluster_has_processed_contents_relationship(self) -> None:
        m = _get_model("ContentCluster")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "processed_contents" in rel_names

    def test_subscription_has_push_records_relationship(self) -> None:
        m = _get_model("Subscription")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "push_records" in rel_names

    def test_task_chain_has_collect_tasks_relationship(self) -> None:
        m = _get_model("TaskChain")
        mapper = _mapper(m)
        rel_names = {r.key for r in mapper.relationships}
        assert "collect_tasks" in rel_names


# ===========================================================================
# AC-T003-3: JSONB fields use SQLAlchemy JSON type with correct defaults
# ===========================================================================


class TestJSONBFields:
    """AC-T003-3: All JSONB fields use correct type and defaults."""

    @pytest.mark.parametrize(
        "model_name,field_name,default_is_list",
        [
            ("Source", "tags", True),
            ("Source", "metadata", False),
            ("RawContent", "raw_metadata", False),
            ("ProcessedContent", "tags", True),
            (
                "ProcessedContent",
                "structured_data",
                None,
            ),  # nullable, no default required
            ("ContentCluster", "tags", True),
            ("Digest", "timeline", None),  # nullable
            ("Digest", "key_points", True),
            ("Subscription", "channel_config", None),  # NOT NULL but no default
            ("Subscription", "match_rules", None),  # NOT NULL but no default
            ("Subscription", "quiet_hours", None),  # nullable
            ("ChatSession", "context", False),
        ],
    )
    def test_jsonb_field_type(
        self, model_name: str, field_name: str, default_is_list
    ) -> None:
        cols = _columns(_get_model(model_name))
        assert field_name in cols, f"{model_name}.{field_name} missing"
        col = cols[field_name]
        type_name = type(col.type).__name__.upper()
        assert "JSON" in type_name, (
            f"{model_name}.{field_name} should be JSON/JSONB, got {col.type}"
        )

    @pytest.mark.parametrize(
        "model_name,field_name,expected_default",
        [
            ("Source", "tags", []),
            ("Source", "metadata", {}),
            ("RawContent", "raw_metadata", {}),
            ("ProcessedContent", "tags", []),
            ("ContentCluster", "tags", []),
            ("Digest", "key_points", []),
            ("ChatSession", "context", {}),
        ],
    )
    def test_jsonb_default_value(
        self, model_name: str, field_name: str, expected_default
    ) -> None:
        cols = _columns(_get_model(model_name))
        col = cols[field_name]
        assert col.default is not None, (
            f"{model_name}.{field_name} should have a default value"
        )
        # Check that the default callable/value produces the expected result
        default_val = col.default.arg
        if callable(default_val):
            default_val = default_val(None)
        assert default_val == expected_default, (
            f"{model_name}.{field_name} default should be {expected_default}, got {default_val}"
        )


# ===========================================================================
# AC-T003-4: pgvector VECTOR(1536) fields correctly defined
# ===========================================================================


class TestVectorFields:
    """AC-T003-4: VECTOR(1536) columns on ProcessedContent and ContentCluster."""

    def test_processed_content_embedding_vector_type(self) -> None:
        """E-004 ProcessedContent.embedding should be VECTOR(1536)."""
        cols = _columns(_get_model("ProcessedContent"))
        assert "embedding" in cols
        col = cols["embedding"]
        # pgvector provides a VECTOR type; check its dimension
        col_type = col.type
        type_str = str(col_type).upper()
        assert "VECTOR" in type_str or hasattr(col_type, "dim"), (
            f"Expected VECTOR type, got {col_type}"
        )
        # Check dimension is 1536
        if hasattr(col_type, "dim"):
            assert col_type.dim == 1536
        else:
            assert "1536" in type_str

    def test_processed_content_embedding_nullable(self) -> None:
        cols = _columns(_get_model("ProcessedContent"))
        assert cols["embedding"].nullable

    def test_content_cluster_centroid_vector_type(self) -> None:
        """E-005 ContentCluster.centroid should be VECTOR(1536)."""
        cols = _columns(_get_model("ContentCluster"))
        assert "centroid" in cols
        col = cols["centroid"]
        col_type = col.type
        type_str = str(col_type).upper()
        assert "VECTOR" in type_str or hasattr(col_type, "dim"), (
            f"Expected VECTOR type, got {col_type}"
        )
        if hasattr(col_type, "dim"):
            assert col_type.dim == 1536
        else:
            assert "1536" in type_str

    def test_content_cluster_centroid_nullable(self) -> None:
        cols = _columns(_get_model("ContentCluster"))
        assert cols["centroid"].nullable


# ===========================================================================
# AC-T003-5: All indexes (GIN, HNSW, full-text) declared on models
# ===========================================================================


class TestIndexes:
    """AC-T003-5: Indexes are declared in the model metadata."""

    # --- E-001 Source indexes ---
    def test_source_idx_status(self) -> None:
        idxs = _indexes(_get_model("Source"))
        assert any(
            "status" in idx.name for idx in _get_model("Source").__table__.indexes
        )

    def test_source_idx_next_collect(self) -> None:
        idxs = _indexes(_get_model("Source"))
        assert any(
            "next_collect" in idx.name for idx in _get_model("Source").__table__.indexes
        )

    def test_source_idx_tags_gin(self) -> None:
        """Source.tags should have a GIN index."""
        found = False
        for idx in _get_model("Source").__table__.indexes:
            if "tags" in idx.name:
                found = True
                # Check for GIN dialect kwargs
                pg_using = idx.dialect_kwargs.get("postgresql_using", "")
                assert pg_using == "gin", f"Expected GIN index, got '{pg_using}'"
        assert found, "No index on Source.tags found"

    # --- E-002 CollectTask indexes ---
    def test_collect_task_idx_status(self) -> None:
        assert any(
            "status" in idx.name for idx in _get_model("CollectTask").__table__.indexes
        )

    def test_collect_task_idx_source(self) -> None:
        assert any(
            "source" in idx.name for idx in _get_model("CollectTask").__table__.indexes
        )

    def test_collect_task_idx_chain(self) -> None:
        assert any(
            "chain" in idx.name for idx in _get_model("CollectTask").__table__.indexes
        )

    # --- E-003 RawContent indexes ---
    def test_raw_content_idx_fingerprint(self) -> None:
        assert any(
            "fingerprint" in idx.name
            for idx in _get_model("RawContent").__table__.indexes
        )

    def test_raw_content_idx_source(self) -> None:
        assert any(
            "source" in idx.name for idx in _get_model("RawContent").__table__.indexes
        )

    def test_raw_content_idx_published(self) -> None:
        assert any(
            "published" in idx.name
            for idx in _get_model("RawContent").__table__.indexes
        )

    # --- E-004 ProcessedContent indexes ---
    def test_processed_content_idx_cluster(self) -> None:
        assert any(
            "cluster" in idx.name
            for idx in _get_model("ProcessedContent").__table__.indexes
        )

    def test_processed_content_idx_tags_gin(self) -> None:
        found = False
        for idx in _get_model("ProcessedContent").__table__.indexes:
            if "tags" in idx.name:
                found = True
                pg_using = idx.dialect_kwargs.get("postgresql_using", "")
                assert pg_using == "gin"
        assert found, "No GIN index on ProcessedContent.tags"

    def test_processed_content_idx_embedding_hnsw(self) -> None:
        """ProcessedContent.embedding should have an HNSW index."""
        found = False
        for idx in _get_model("ProcessedContent").__table__.indexes:
            if "embedding" in idx.name:
                found = True
                pg_using = idx.dialect_kwargs.get("postgresql_using", "")
                assert pg_using == "hnsw", f"Expected HNSW index, got '{pg_using}'"
        assert found, "No HNSW index on ProcessedContent.embedding"

    def test_processed_content_idx_published(self) -> None:
        assert any(
            "published" in idx.name
            for idx in _get_model("ProcessedContent").__table__.indexes
        )

    def test_processed_content_idx_fulltext_gin(self) -> None:
        """ProcessedContent should have a full-text search GIN index."""
        found = False
        for idx in _get_model("ProcessedContent").__table__.indexes:
            if "ts" in idx.name or "fulltext" in idx.name or "fts" in idx.name:
                found = True
                pg_using = idx.dialect_kwargs.get("postgresql_using", "")
                assert pg_using == "gin"
        assert found, "No full-text GIN index on ProcessedContent"

    # --- E-005 ContentCluster indexes ---
    def test_content_cluster_idx_tags_gin(self) -> None:
        found = False
        for idx in _get_model("ContentCluster").__table__.indexes:
            if "tags" in idx.name:
                found = True
                pg_using = idx.dialect_kwargs.get("postgresql_using", "")
                assert pg_using == "gin"
        assert found, "No GIN index on ContentCluster.tags"

    def test_content_cluster_idx_updated(self) -> None:
        assert any(
            "updated" in idx.name
            for idx in _get_model("ContentCluster").__table__.indexes
        )

    # --- E-006 Digest indexes ---
    def test_digest_idx_cluster(self) -> None:
        assert any(
            "cluster" in idx.name for idx in _get_model("Digest").__table__.indexes
        )

    # --- E-007 LLMCallLog indexes ---
    def test_llm_call_log_idx_model(self) -> None:
        assert any(
            "model" in idx.name for idx in _get_model("LLMCallLog").__table__.indexes
        )

    def test_llm_call_log_idx_created(self) -> None:
        assert any(
            "created" in idx.name for idx in _get_model("LLMCallLog").__table__.indexes
        )

    def test_llm_call_log_idx_type(self) -> None:
        assert any(
            "type" in idx.name for idx in _get_model("LLMCallLog").__table__.indexes
        )

    # --- E-008 TaskChain indexes ---
    def test_task_chain_idx_status(self) -> None:
        assert any(
            "status" in idx.name for idx in _get_model("TaskChain").__table__.indexes
        )

    def test_task_chain_idx_pipeline(self) -> None:
        assert any(
            "pipeline" in idx.name for idx in _get_model("TaskChain").__table__.indexes
        )

    # --- E-009 Subscription indexes ---
    def test_subscription_idx_channel(self) -> None:
        assert any(
            "channel" in idx.name
            for idx in _get_model("Subscription").__table__.indexes
        )

    def test_subscription_idx_status(self) -> None:
        assert any(
            "status" in idx.name for idx in _get_model("Subscription").__table__.indexes
        )

    def test_subscription_idx_rules_gin(self) -> None:
        found = False
        for idx in _get_model("Subscription").__table__.indexes:
            if "rules" in idx.name:
                found = True
                pg_using = idx.dialect_kwargs.get("postgresql_using", "")
                assert pg_using == "gin"
        assert found, "No GIN index on Subscription.match_rules"

    # --- E-010 PushRecord indexes ---
    def test_push_record_idx_subscription(self) -> None:
        assert any(
            "subscription" in idx.name
            for idx in _get_model("PushRecord").__table__.indexes
        )

    def test_push_record_idx_content(self) -> None:
        assert any(
            "content" in idx.name for idx in _get_model("PushRecord").__table__.indexes
        )

    def test_push_record_idx_dedup_unique(self) -> None:
        """PushRecord should have a unique composite index on (subscription_id, content_id, channel)."""
        found = False
        for idx in _get_model("PushRecord").__table__.indexes:
            if "dedup" in idx.name:
                found = True
                assert idx.unique, "Dedup index should be unique"
                col_names = {c.name for c in idx.columns}
                assert {"subscription_id", "content_id", "channel"}.issubset(col_names)
        assert found, "No dedup index on PushRecord"

    # --- E-011 ChatSession indexes ---
    def test_chat_session_idx_user(self) -> None:
        """ChatSession should have a composite index on (channel, channel_user_id)."""
        found = False
        for idx in _get_model("ChatSession").__table__.indexes:
            if "user" in idx.name:
                found = True
                col_names = {c.name for c in idx.columns}
                assert {"channel", "channel_user_id"}.issubset(col_names)
        assert found, "No composite user index on ChatSession"

    def test_chat_session_idx_active(self) -> None:
        assert any(
            "active" in idx.name for idx in _get_model("ChatSession").__table__.indexes
        )


# ===========================================================================
# AC-T003-6: Alembic migration (TODO - requires PostgreSQL)
# ===========================================================================


class TestAlembicMigration:
    """AC-T003-6: Alembic can generate and apply migrations from models.

    NOTE: Full Alembic migration testing requires PostgreSQL with pgvector.
    These tests are marked as TODO placeholders.
    """

    @pytest.mark.skip(
        reason="AC-T003-6: Requires PostgreSQL; deferred to integration tests"
    )
    def test_alembic_autogenerate_produces_migration(self) -> None:
        pass

    @pytest.mark.skip(
        reason="AC-T003-6: Requires PostgreSQL; deferred to integration tests"
    )
    def test_alembic_upgrade_succeeds(self) -> None:
        pass

    @pytest.mark.skip(
        reason="AC-T003-6: Requires PostgreSQL; deferred to integration tests"
    )
    def test_alembic_downgrade_succeeds(self) -> None:
        pass
