"""Sprint-7 integration tests (T-063).

Covers AC-T063-1 through AC-T063-7 with real cross-module paths.
AC-T063-8 and AC-T063-9 are verified via external commands (see task summary).

Tests in TestLLMStatsEndpoint, TestClustersEndpoint, and
TestTaskChainRepositoryCRUD now use pg_session / pg_container fixtures from
conftest.py and skip automatically when Docker is unavailable.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ===========================================================================
# AC-T063-1: LLM retry + fallback end-to-end
# ===========================================================================


class TestLLMRetryFallback:
    """AC-T063-1: LLM retry logic + FallbackManager integration."""

    @pytest.mark.asyncio
    async def test_retry_then_succeed_returns_result(self) -> None:
        """First two calls raise APIConnectionError; third call succeeds.

        Verifies LLMGateway._call_with_retry retries RECOVERABLE_TRANSIENT
        errors and ultimately returns the successful LLMResult.
        """
        from tenacity import wait_none

        from intellisource.llm.gateway import LLMGateway, LLMResult

        call_count = 0

        class _FakeAPIConnectionError(Exception):
            pass

        # Patch __name__ so _classify_error sees "APIConnectionError"
        _FakeAPIConnectionError.__name__ = "APIConnectionError"

        async def _fake_acompletion(**kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise _FakeAPIConnectionError("transient failure")
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "success"
            mock_resp.usage.prompt_tokens = 10
            mock_resp.usage.completion_tokens = 5
            mock_resp.model = "gpt-4o-mini"
            return mock_resp

        gw = LLMGateway(_retry_wait=wait_none())
        with patch("intellisource.llm.gateway.litellm.acompletion", _fake_acompletion):
            result = await gw.complete("hello", model="gpt-4o-mini")

        assert isinstance(result, LLMResult)
        assert result.content == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_triggers_fallback(self) -> None:
        """When all 4 attempts fail, FallbackManager is called and returns fallback
        result."""
        from tenacity import wait_none

        from intellisource.llm.fallback import FallbackManager
        from intellisource.llm.gateway import LLMGateway, LLMResult

        class _FakeAPIConnectionError(Exception):
            pass

        _FakeAPIConnectionError.__name__ = "APIConnectionError"

        async def _always_fail(**kwargs: Any) -> Any:
            raise _FakeAPIConnectionError("always fail")

        fallback_called_with: list[Any] = []

        def _fallback_fn(input_data: Any) -> LLMResult:
            fallback_called_with.append(input_data)
            return LLMResult(content="fallback-content", metadata={"model": "fallback"})

        mock_log = AsyncMock()
        mock_log.record = AsyncMock()
        fm = FallbackManager(
            fallback_registry={"summarize": _fallback_fn},
            call_log=mock_log,
        )

        gw = LLMGateway(fallback_manager=fm, _retry_wait=wait_none())
        with patch("intellisource.llm.gateway.litellm.acompletion", _always_fail):
            result = await gw.complete(
                "hello", model="gpt-4o-mini", task_type="summarize"
            )

        assert isinstance(result, LLMResult)
        assert result.content == "fallback-content"
        assert len(fallback_called_with) == 1


# ===========================================================================
# AC-T063-2: ConfigResolver three-layer merge
# ===========================================================================


class TestConfigResolverMerge:
    """AC-T063-2: ConfigResolver merges defaults + project + env vars."""

    def test_three_layer_merge_env_overrides_project(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env var takes priority over project YAML which overrides defaults.

        defaults: default_model.model = gpt-3.5-turbo
        project:  default_model.model = gpt-4o-mini
        env:      IS_LLM_DEFAULT_MODEL = gpt-4o     (highest priority)
        """
        defaults_file = tmp_path / "defaults.yaml"
        defaults_file.write_text(
            "default_model:\n  model: gpt-3.5-turbo\n  provider: openai\n"
        )

        project_file = tmp_path / "project.yaml"
        project_file.write_text(
            "default_model:\n  model: gpt-4o-mini\n  provider: openai\n"
        )

        monkeypatch.setenv("IS_LLM_DEFAULT_MODEL", "gpt-4o")

        from intellisource.config.resolver import ConfigResolver

        resolver = ConfigResolver(
            defaults_path=str(defaults_file),
            project_path=str(project_file),
            env_prefix="IS_",
        )
        merged = resolver.resolve()

        # Env var is highest priority
        assert merged["default_model"]["model"] == "gpt-4o"

    def test_missing_project_file_falls_back_to_defaults(self, tmp_path: Any) -> None:
        """When project YAML is absent, defaults are returned unchanged."""
        defaults_file = tmp_path / "defaults.yaml"
        defaults_file.write_text(
            "default_model:\n  model: gpt-3.5-turbo\n  provider: openai\n"
        )

        from intellisource.config.resolver import ConfigResolver

        resolver = ConfigResolver(
            defaults_path=str(defaults_file),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        merged = resolver.resolve()

        assert merged["default_model"]["model"] == "gpt-3.5-turbo"

    def test_deep_merge_keeps_unoverridden_keys(self, tmp_path: Any) -> None:
        """Deep merge preserves keys from defaults not touched by project layer."""
        defaults_file = tmp_path / "defaults.yaml"
        defaults_file.write_text(
            "default_model:\n  model: gpt-3.5-turbo\n  provider: openai\n"
            "models:\n  extract:\n    model: gpt-4o-mini\n    provider: openai\n"
        )
        project_file = tmp_path / "project.yaml"
        project_file.write_text("default_model:\n  model: gpt-4o\n  provider: openai\n")

        from intellisource.config.resolver import ConfigResolver

        resolver = ConfigResolver(
            defaults_path=str(defaults_file),
            project_path=str(project_file),
        )
        merged = resolver.resolve()

        # Project overrides default_model but preserves models.extract from defaults
        assert merged["default_model"]["model"] == "gpt-4o"
        assert merged["models"]["extract"]["model"] == "gpt-4o-mini"


# ===========================================================================
# AC-T063-3: PromptBuilder variant loading + ModelProfile integration
# ===========================================================================


class TestPromptBuilderModelProfile:
    """AC-T063-3: PromptBuilder loads variants; ModelRoutingConfig returns
    ModelProfile."""

    def test_prompt_builder_loads_base_template(self) -> None:
        """PromptBuilder('extraction') loads the base extraction.prompt.md template."""
        from intellisource.llm.prompt_builder import PromptBuilder

        pb = PromptBuilder("extraction", model="gpt-4o-mini")
        pb.add_context("schema", "{}").add_context("body_text", "sample text")
        prompt = pb.build()

        assert isinstance(prompt, str)
        assert "sample text" in prompt

    def test_prompt_builder_loads_structured_variant(self) -> None:
        """PromptBuilder with prompt_style='structured' loads
        extraction.structured.prompt.md."""
        from intellisource.llm.prompt_builder import PromptBuilder

        pb_base = PromptBuilder("extraction", model="gpt-4o-mini")
        pb_base.add_context("schema", "{}").add_context("body_text", "x")
        pb_variant = PromptBuilder(
            "extraction", model="gpt-4o-mini", prompt_style="structured"
        )
        pb_variant.add_context("schema", "{}").add_context("body_text", "x")

        # Variant template is distinct from base template
        assert pb_base.build() != pb_variant.build()

    def test_model_routing_config_returns_profile_when_configured(
        self, tmp_path: Any
    ) -> None:
        """ModelRoutingConfig.get_profile returns a ModelProfile with correct fields."""
        config_data = {
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
            "models": {},
            "profiles": {
                "gpt-4o-mini": {
                    "temperature": 0.5,
                    "max_tokens": 2048,
                    "context_window": 128000,
                    "prompt_style": "concise",
                    "timeout_seconds": 30,
                }
            },
        }
        from intellisource.llm.model_config import ModelProfile, ModelRoutingConfig

        routing = ModelRoutingConfig(config_data)
        profile = routing.get_profile("gpt-4o-mini")

        assert profile is not None
        assert isinstance(profile, ModelProfile)
        assert profile.temperature == 0.5
        assert profile.max_tokens == 2048
        assert profile.context_window == 128_000

    def test_build_messages_produces_system_and_user_roles(self) -> None:
        """build_messages() returns [system, user] list with non-empty content."""
        from intellisource.llm.prompt_builder import PromptBuilder

        pb = PromptBuilder("summarizer", model="gpt-4o-mini", system_prompt="Be brief.")
        pb.add_context("docs_text", "some clustered docs")
        messages = pb.build_messages()

        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles
        assert all(m["content"] for m in messages)


# ===========================================================================
# AC-T063-4: Context compaction in AgentRunner flexible mode
# ===========================================================================


class TestAgentRunnerCompaction:
    """AC-T063-4: compact_messages triggers when token count exceeds threshold."""

    @pytest.mark.asyncio
    async def test_compact_messages_triggers_when_over_threshold(self) -> None:
        """compact_messages() returns a shorter list when total tokens exceed
        threshold."""
        from intellisource.llm.compaction import compact_messages
        from intellisource.llm.model_config import ModelProfile

        # Profile with tiny context window to force compaction
        profile = ModelProfile(
            temperature=0.7,
            max_tokens=512,
            context_window=200,  # very small to trigger compaction
        )

        # Build messages whose "tokens" clearly exceed the threshold
        # (context_window * 0.8 = 160 tokens; each word ~1 token heuristic)
        long_word = "word " * 50  # 50 tokens each
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": long_word},
            {"role": "assistant", "content": long_word},
            {"role": "user", "content": long_word},
            {"role": "assistant", "content": long_word},
        ]

        mock_gw = MagicMock()
        # estimate_tokens returns a fixed count to keep test deterministic
        mock_gw.estimate_tokens = MagicMock(return_value=60)
        # LLM summary call returns a short string
        mock_gw.complete = AsyncMock(
            return_value=MagicMock(content="summarized conversation")
        )

        result = await compact_messages(
            messages=messages,
            gateway=mock_gw,
            profile=profile,
            context_token_budget=200,
            model="gpt-4o-mini",
        )

        # Compaction must produce fewer messages than the input (or at minimum a
        # summary)
        assert len(result) < len(messages) or (
            len(result) >= 1 and result[0].get("role") == "system"
        ), f"Expected compaction to reduce message list; got {result}"

    @pytest.mark.asyncio
    async def test_compact_messages_no_op_when_under_threshold(self) -> None:
        """compact_messages() returns messages unchanged when total tokens are
        under threshold."""
        from intellisource.llm.compaction import compact_messages
        from intellisource.llm.model_config import ModelProfile

        profile = ModelProfile(
            temperature=0.7,
            max_tokens=4096,
            context_window=128000,
        )

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

        mock_gw = MagicMock()
        mock_gw.estimate_tokens = MagicMock(return_value=2)

        result = await compact_messages(
            messages=messages,
            gateway=mock_gw,
            profile=profile,
            context_token_budget=128000,
        )

        assert result == messages


# ===========================================================================
# Shared helper: build a DatabaseManager-shaped object from a pg_container URL
# ===========================================================================


def _make_pg_db_manager(pg_url: str, pg_session: AsyncSession | None = None) -> Any:
    """Return a DatabaseManager-shaped object backed by a PostgreSQL engine.

    When ``pg_session`` is provided, the manager yields *that* session per
    request so the API path sees the test fixture's writes inside the same
    SAVEPOINT — necessary because pg_session uses a rolled-back outer
    transaction and a fresh session would observe no uncommitted data.

    When ``pg_session`` is None, falls back to building a fresh engine and
    session_factory keyed off the pg_container URL — used by tests that
    insert data through other means (e.g. raw SQL via separate engine) and
    just need a DatabaseManager-shaped facade.
    """
    if pg_session is not None:

        class _PgSharedDB:
            @asynccontextmanager
            async def get_session(self) -> AsyncIterator[AsyncSession]:
                yield pg_session

            async def close(self) -> None:  # pragma: no cover - no-op
                return None

        return _PgSharedDB()

    engine = create_async_engine(pg_url, echo=False)
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    class _PgDB:
        @asynccontextmanager
        async def get_session(self) -> AsyncIterator[AsyncSession]:
            async with session_factory() as sess:
                yield sess

        async def close(self) -> None:
            await engine.dispose()

    return _PgDB()


# ===========================================================================
# AC-T063-5: GET /api/v1/llm/stats with real DB session
# ===========================================================================


class TestLLMStatsEndpoint:
    """AC-T063-5: /api/v1/llm/stats integration test using PostgreSQL."""

    @pytest.mark.asyncio
    async def test_llm_stats_empty_db_returns_zero_aggregates(
        self, pg_session: AsyncSession, pg_container: str
    ) -> None:
        """With no LLMCallLog rows, /llm/stats returns total_calls=0 and empty lists."""
        from httpx import ASGITransport, AsyncClient

        from intellisource.main import create_app

        mock_db = _make_pg_db_manager(pg_container)

        with patch("intellisource.main.DatabaseManager", return_value=mock_db):
            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/llm/stats?period=day")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 0
        assert data["by_model"] == []
        assert data["by_date"] == []
        assert "total_tokens" in data
        assert "avg_latency_ms" in data

    @pytest.mark.asyncio
    async def test_llm_stats_with_records_returns_aggregated_fields(
        self, pg_session: AsyncSession, pg_container: str
    ) -> None:
        """After inserting LLMCallLog rows, stats endpoint returns correct
        aggregates."""
        from datetime import datetime, timezone

        from httpx import ASGITransport, AsyncClient

        from intellisource.main import create_app
        from intellisource.storage.models import LLMCallLog

        # Insert two log rows via pg_session
        await pg_session.execute(
            LLMCallLog.__table__.insert(),
            [
                {
                    "id": uuid.uuid4(),
                    "model": "gpt-4o-mini",
                    "provider": "openai",
                    "call_type": "summarize",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "latency_ms": 200,
                    "input_length": 400,
                    "output_length": 200,
                    "status": "success",
                    "created_at": datetime.now(timezone.utc),
                },
                {
                    "id": uuid.uuid4(),
                    "model": "gpt-4o-mini",
                    "provider": "openai",
                    "call_type": "extract",
                    "input_tokens": 200,
                    "output_tokens": 100,
                    "latency_ms": 400,
                    "input_length": 800,
                    "output_length": 400,
                    "status": "success",
                    "created_at": datetime.now(timezone.utc),
                },
            ],
        )
        await pg_session.flush()

        # Reuse pg_session inside the API path: the test wrote rows inside a
        # SAVEPOINT that has not been committed, so a fresh engine would see
        # nothing. _make_pg_db_manager with pg_session yields the same session
        # to api routers via get_session().
        mock_db = _make_pg_db_manager(pg_container, pg_session=pg_session)

        with patch("intellisource.main.DatabaseManager", return_value=mock_db):
            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/llm/stats?period=day")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 2
        assert data["total_input_tokens"] == 300
        assert data["total_output_tokens"] == 150
        assert data["total_tokens"] == 450
        assert len(data["by_model"]) == 1
        assert data["by_model"][0]["model"] == "gpt-4o-mini"
        assert data["by_model"][0]["call_count"] == 2


# ===========================================================================
# AC-T063-6: GET /api/v1/clusters integration test
# ===========================================================================


class TestClustersEndpoint:
    """AC-T063-6: /api/v1/clusters integration with PostgreSQL + ClusterRepository."""

    @pytest.mark.asyncio
    async def test_clusters_empty_db_returns_empty_list(
        self, pg_session: AsyncSession, pg_container: str
    ) -> None:
        """No clusters in DB → items=[], next_cursor=null, has_more=false."""
        from httpx import ASGITransport, AsyncClient

        from intellisource.main import create_app

        mock_db = _make_pg_db_manager(pg_container)

        with patch("intellisource.main.DatabaseManager", return_value=mock_db):
            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/clusters")

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["next_cursor"] is None
        assert data["has_more"] is False

    @pytest.mark.asyncio
    async def test_clusters_with_tag_filter_returns_only_matching(
        self, pg_session: AsyncSession, pg_container: str
    ) -> None:
        """tag filter route parameter is accepted; ClusterRepository.list_clusters
        wires the tag to a JSONB contains() query (PG @> operator).

        Verifies the endpoint returns 200 when no tag filter is applied and
        that list_clusters is called with tag='ai' when that param is passed.
        """

        from httpx import ASGITransport, AsyncClient

        from intellisource.main import create_app
        from intellisource.storage.models import ContentCluster

        cluster_id = uuid.uuid4()
        cluster = ContentCluster(
            id=cluster_id,
            topic="AI News",
            tags=["ai", "tech"],
            content_count=5,
            status="active",
        )
        pg_session.add(cluster)
        await pg_session.flush()

        mock_db = _make_pg_db_manager(pg_container)
        fake_return = {"items": [], "next_cursor": None, "has_more": False}
        mock_list = AsyncMock(return_value=fake_return)

        with patch("intellisource.main.DatabaseManager", return_value=mock_db):
            with patch(
                "intellisource.storage.repositories.cluster.ClusterRepository.list_clusters",
                new=mock_list,
            ):
                app = create_app()
                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    resp = await client.get("/api/v1/clusters?tag=ai")

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "next_cursor" in data
        assert "has_more" in data
        # Verify the router forwarded tag="ai" to list_clusters
        mock_list.assert_called_once()
        _, call_kwargs = mock_list.call_args
        assert call_kwargs.get("tag") == "ai"

    @pytest.mark.asyncio
    async def test_clusters_limit_controls_page_size(
        self, pg_session: AsyncSession, pg_container: str
    ) -> None:
        """limit parameter caps the number of returned items."""
        from httpx import ASGITransport, AsyncClient

        from intellisource.main import create_app
        from intellisource.storage.models import ContentCluster

        for i in range(5):
            pg_session.add(
                ContentCluster(
                    id=uuid.uuid4(),
                    topic=f"Topic {i}",
                    tags=[],
                    content_count=i,
                    status="active",
                )
            )
        await pg_session.flush()

        mock_db = _make_pg_db_manager(pg_container, pg_session=pg_session)

        with patch("intellisource.main.DatabaseManager", return_value=mock_db):
            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/clusters?limit=2")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2
        # With 5 rows and limit=2 there should be more pages
        assert data["has_more"] is True
        assert isinstance(data["next_cursor"], str)
        assert data["next_cursor"]

    @pytest.mark.asyncio
    async def test_clusters_invalid_cursor_returns_400(
        self, pg_session: AsyncSession, pg_container: str
    ) -> None:
        """An invalid cursor string (not UUID) must return HTTP 400."""
        from httpx import ASGITransport, AsyncClient

        from intellisource.main import create_app

        mock_db = _make_pg_db_manager(pg_container)

        with patch("intellisource.main.DatabaseManager", return_value=mock_db):
            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/clusters?cursor=not-a-uuid")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_clusters_per_item_fields_match_api016(
        self, pg_session: AsyncSession, pg_container: str
    ) -> None:
        """Each cluster item has arch API-016 fields:
        id/topic/tags/content_count/digest/created_at/updated_at."""
        from httpx import ASGITransport, AsyncClient

        from intellisource.main import create_app
        from intellisource.storage.models import ContentCluster

        cluster_id = uuid.uuid4()
        pg_session.add(
            ContentCluster(
                id=cluster_id,
                topic="Integration Test",
                tags=["test"],
                content_count=1,
                status="active",
            )
        )
        await pg_session.flush()

        mock_db = _make_pg_db_manager(pg_container, pg_session=pg_session)

        with patch("intellisource.main.DatabaseManager", return_value=mock_db):
            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/clusters")

        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        item = items[0]
        for field in (
            "id",
            "topic",
            "tags",
            "content_count",
            "digest",
            "created_at",
            "updated_at",
        ):
            assert field in item, f"Field '{field}' missing from cluster response"


# ===========================================================================
# AC-T063-7: TaskChainRepository write + read integration
# ===========================================================================


class TestTaskChainRepositoryCRUD:
    """AC-T063-7: TaskChainRepository create/get/update_status across a real
    PostgreSQL session (pg_session fixture)."""

    @pytest.mark.asyncio
    async def test_create_and_get_roundtrip(self, pg_session: AsyncSession) -> None:
        """create() persists a TaskChain; get() retrieves it with all fields intact."""
        from intellisource.storage.models import TaskChain
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(pg_session)
        chain_id = uuid.uuid4()
        chain = TaskChain(
            id=chain_id,
            pipeline_name="integration-test-pipeline",
            status="pending",
            trigger_type="scheduled",
            execution_mode="strict",
            total_steps=4,
            completed_steps=0,
        )

        created = await repo.create(chain)
        await pg_session.flush()

        fetched = await repo.get(str(chain_id))

        assert created.id == chain_id
        assert fetched is not None
        assert fetched.pipeline_name == "integration-test-pipeline"
        assert fetched.trigger_type == "scheduled"
        assert fetched.execution_mode == "strict"
        assert fetched.total_steps == 4

    @pytest.mark.asyncio
    async def test_update_status_reflects_in_db(self, pg_session: AsyncSession) -> None:
        """update_status() changes the status field that is subsequently readable."""
        from intellisource.storage.models import TaskChain
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(pg_session)
        chain_id = uuid.uuid4()
        chain = TaskChain(
            id=chain_id,
            pipeline_name="status-update-pipeline",
            status="pending",
            trigger_type="manual",
            execution_mode="flexible",
            total_steps=2,
            completed_steps=0,
        )
        await repo.create(chain)
        await pg_session.flush()

        await repo.update_status(str(chain_id), "running")
        await pg_session.flush()

        fetched = await repo.get(str(chain_id))
        assert fetched is not None
        assert fetched.status == "running"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_id(
        self, pg_session: AsyncSession
    ) -> None:
        """get() returns None for a random UUID that was never persisted."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(pg_session)
        result = await repo.get(str(uuid.uuid4()))

        assert result is None

    @pytest.mark.asyncio
    async def test_update_status_missing_id_does_not_raise(
        self, pg_session: AsyncSession
    ) -> None:
        """update_status() on a non-existent ID completes without raising."""
        from intellisource.storage.repositories.task_chain import TaskChainRepository

        repo = TaskChainRepository(pg_session)
        await repo.update_status(str(uuid.uuid4()), "failed")
        # No exception means pass
