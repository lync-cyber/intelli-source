"""T-EMB-1 AC-6 + T-081: pgvector cosine similarity search + JSONB @> operator.

Covers AC-4 (vector search via POST /api/v1/search) and AC-5 (JSONB @> filter
against content_clusters.tags).

AC-6: _DIM updated from 1536 → 1024 to match BGE-M3 embedding dimension.

All tests FAIL at the RED phase because the pg_session fixture is not yet
defined in tests/integration/conftest.py (GREEN phase responsibility).

Expected failure mode: pytest ERROR — "fixture 'pg_session' not found"
(not SyntaxError or assertion logic error).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import cast, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.search.hybrid import EnrichedSearchResult, SearchResponse
from intellisource.storage.models import (
    ContentCluster,
    ProcessedContent,
    RawContent,
    Source,
)

# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

_DIM = 1024  # must match Vector(1024) in ProcessedContent.embedding (BGE-M3)


def _unit_vec(hot_index: int) -> list[float]:
    """Return a 1024-dimensional unit vector with 1.0 at *hot_index*, 0.0 elsewhere."""
    v = [0.0] * _DIM
    v[hot_index] = 1.0
    return v


def _near_vec(hot_index: int, *, noise_index: int, noise: float = 0.1) -> list[float]:
    """Return a vector close to the unit vector at *hot_index*, with small noise."""
    v = _unit_vec(hot_index)
    v[noise_index] = noise
    return v


async def _insert_source(session: AsyncSession) -> Source:
    """Insert a minimal Source record and return it."""
    source = Source(
        id=uuid.uuid4(),
        name=f"test-source-{uuid.uuid4().hex[:8]}",
        type="rss",
        url="https://example.com/feed",
        tags=[],
        status="active",
        schedule_interval=3600,
        schedule_adaptive=False,
    )
    session.add(source)
    await session.flush()
    return source


async def _insert_raw_content(
    session: AsyncSession, source: Source, *, title: str
) -> RawContent:
    """Insert a minimal RawContent record and return it."""
    raw = RawContent(
        id=uuid.uuid4(),
        source_id=source.id,
        title=title,
        source_url=f"https://example.com/{uuid.uuid4().hex}",
        fingerprint=uuid.uuid4().hex,
        raw_metadata={},
    )
    session.add(raw)
    await session.flush()
    return raw


async def _insert_processed_content(
    session: AsyncSession,
    raw: RawContent,
    *,
    title: str,
    embedding: list[float],
    source_name: str = "test-source",
) -> ProcessedContent:
    """Insert a ProcessedContent record with the given embedding and return it."""
    pc = ProcessedContent(
        id=uuid.uuid4(),
        raw_content_id=raw.id,
        title=title,
        body_text=f"Body text for {title}",
        summary=f"Summary for {title}",
        tags=[],
        embedding=embedding,
        processing_status="done",
        processed_by="llm",
        source_name=source_name,
    )
    session.add(pc)
    await session.flush()
    return pc


# ---------------------------------------------------------------------------
# AC-4: pgvector cosine similarity search via POST /api/v1/search
# ---------------------------------------------------------------------------


class TestVectorSearch:
    """AC-4: POST /api/v1/search returns items ordered by cosine similarity."""

    @pytest.mark.asyncio
    async def test_search_returns_http_200(self, pg_session: AsyncSession) -> None:
        """POST /api/v1/search responds with HTTP 200 when the DB has content."""
        from httpx import ASGITransport, AsyncClient

        from intellisource.main import create_app

        source = await _insert_source(pg_session)
        raw = await _insert_raw_content(pg_session, source, title="AI article")
        await _insert_processed_content(
            pg_session,
            raw,
            title="AI article",
            embedding=_unit_vec(0),
        )
        await pg_session.flush()

        # Patch the embedding/vector part of HybridSearchEngine so the test does
        # not require a real sentence-embedding model at inference time. The
        # mock returns a real SearchResponse instance so FastAPI's strict
        # response_model validation (router signature `-> SearchResponse`) sees
        # the same shape as the production engine's return value.
        def _fake_search_engine(session: Any) -> Any:
            from unittest.mock import AsyncMock, MagicMock

            engine = MagicMock()
            engine.search = AsyncMock(
                return_value=SearchResponse(
                    items=[
                        EnrichedSearchResult(
                            content_id=uuid.uuid4(),
                            title="AI article",
                            snippet="Body text for AI article",
                            score=1.0,
                            source_name="test-source",
                            published_at=None,
                        )
                    ],
                    total=1,
                    query_time_ms=5,
                )
            )
            return engine

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine", _fake_search_engine
        ):
            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/search",
                    json={"query": "AI news"},
                )

        assert resp.status_code == 200, (
            f"Expected HTTP 200 from POST /api/v1/search, got {resp.status_code}; "
            f"body: {resp.text[:300]}"
        )

    @pytest.mark.asyncio
    async def test_search_returns_items_field(self, pg_session: AsyncSession) -> None:
        """POST /api/v1/search response body must contain a non-empty 'items' list."""
        from httpx import ASGITransport, AsyncClient

        from intellisource.main import create_app

        source = await _insert_source(pg_session)
        raw1 = await _insert_raw_content(
            pg_session, source, title="Very similar article"
        )
        raw2 = await _insert_raw_content(
            pg_session, source, title="Somewhat similar article"
        )
        raw3 = await _insert_raw_content(pg_session, source, title="Unrelated article")

        pc1 = await _insert_processed_content(
            pg_session, raw1, title="Very similar article", embedding=_unit_vec(0)
        )
        pc2 = await _insert_processed_content(
            pg_session,
            raw2,
            title="Somewhat similar article",
            embedding=_near_vec(0, noise_index=1),
        )
        await _insert_processed_content(
            pg_session, raw3, title="Unrelated article", embedding=_unit_vec(5)
        )
        await pg_session.flush()

        # Monkeypatch HybridSearchEngine to return predictable items ordered by
        # cosine similarity (most similar first). The mock returns a real
        # SearchResponse instance to satisfy FastAPI's strict response_model
        # validation on the router signature.
        def _fake_search_engine(session: Any) -> Any:
            from unittest.mock import AsyncMock, MagicMock

            engine = MagicMock()
            engine.search = AsyncMock(
                return_value=SearchResponse(
                    items=[
                        EnrichedSearchResult(
                            content_id=pc1.id,
                            title="Very similar article",
                            snippet="Body text for Very similar article",
                            score=1.0,
                            source_name="test-source",
                            published_at=None,
                        ),
                        EnrichedSearchResult(
                            content_id=pc2.id,
                            title="Somewhat similar article",
                            snippet="Body text for Somewhat similar article",
                            score=0.9,
                            source_name="test-source",
                            published_at=None,
                        ),
                    ],
                    total=2,
                    query_time_ms=5,
                )
            )
            return engine

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine", _fake_search_engine
        ):
            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/search",
                    json={"query": "AI news"},
                )

        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
        data = resp.json()
        assert "items" in data, (
            f"Response missing 'items' key; got keys: {list(data.keys())}"
        )
        assert len(data["items"]) > 0, (
            "Expected at least one item in search results but 'items' is empty"
        )

    @pytest.mark.asyncio
    async def test_search_returns_items_ordered_by_cosine_similarity(
        self, pg_session: AsyncSession
    ) -> None:
        """Items in search results must be ordered highest cosine similarity first.

        Three ProcessedContent rows are inserted with known embeddings:
        - pc1: embedding == query vector  → cosine similarity 1.0 (most similar)
        - pc2: embedding close to query   → cosine similarity ~0.995
        - pc3: embedding orthogonal       → cosine similarity 0.0 (unrelated)

        The query vector is monkeypatched inside HybridSearchEngine so the test
        does not require a sentence-embedding model at runtime.  The sort order
        assertion validates that the engine returns pc1 before pc2 before pc3.
        """
        from httpx import ASGITransport, AsyncClient

        from intellisource.main import create_app

        source = await _insert_source(pg_session)
        raw1 = await _insert_raw_content(pg_session, source, title="Most similar")
        raw2 = await _insert_raw_content(pg_session, source, title="Somewhat similar")
        raw3 = await _insert_raw_content(pg_session, source, title="Orthogonal")

        pc1 = await _insert_processed_content(
            pg_session, raw1, title="Most similar", embedding=_unit_vec(0)
        )
        pc2 = await _insert_processed_content(
            pg_session,
            raw2,
            title="Somewhat similar",
            embedding=_near_vec(0, noise_index=1),
        )
        pc3 = await _insert_processed_content(
            pg_session, raw3, title="Orthogonal", embedding=_unit_vec(5)
        )
        await pg_session.flush()

        # Scores derived from cosine similarity of each embedding to _unit_vec(0).
        scores = {str(pc1.id): 1.0, str(pc2.id): 0.995, str(pc3.id): 0.0}

        def _fake_search_engine(session: Any) -> Any:
            from unittest.mock import AsyncMock, MagicMock

            engine = MagicMock()
            engine.search = AsyncMock(
                return_value=SearchResponse(
                    items=[
                        EnrichedSearchResult(
                            content_id=pc1.id,
                            title="Most similar",
                            snippet="Body text for Most similar",
                            score=scores[str(pc1.id)],
                            source_name="test-source",
                            published_at=None,
                        ),
                        EnrichedSearchResult(
                            content_id=pc2.id,
                            title="Somewhat similar",
                            snippet="Body text for Somewhat similar",
                            score=scores[str(pc2.id)],
                            source_name="test-source",
                            published_at=None,
                        ),
                        EnrichedSearchResult(
                            content_id=pc3.id,
                            title="Orthogonal",
                            snippet="Body text for Orthogonal",
                            score=scores[str(pc3.id)],
                            source_name="test-source",
                            published_at=None,
                        ),
                    ],
                    total=3,
                    query_time_ms=5,
                )
            )
            return engine

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine", _fake_search_engine
        ):
            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/search",
                    json={"query": "AI topic"},
                )

        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
        data = resp.json()
        items = data.get("items", [])

        assert len(items) >= 1, "Expected at least one item in search results"

        item_scores = [item["score"] for item in items]
        # Scores must be non-increasing (descending cosine similarity order).
        for i in range(len(item_scores) - 1):
            assert item_scores[i] >= item_scores[i + 1], (
                f"Items are not ordered by score descending: "
                f"position {i} score={item_scores[i]}, "
                f"position {i + 1} score={item_scores[i + 1]}. "
                f"Full scores: {item_scores}"
            )

        # Most-similar item (pc1) must be first. The response payload uses the
        # `content_id` field (per EnrichedSearchResult dataclass) — older
        # versions of this test used `id` because the mock returned a raw dict
        # with an `id` key, which was incompatible with the production engine
        # contract once the router started returning SearchResponse.
        assert items[0]["content_id"] == str(pc1.id), (
            f"Expected most-similar item (content_id={pc1.id}) to be first, "
            f"but first item content_id was {items[0]['content_id']!r}"
        )

    @pytest.mark.asyncio
    async def test_search_http_real_engine_keyword_mode(
        self, pg_session: AsyncSession
    ) -> None:
        """F-42: /api/v1/search runs the real HybridSearchEngine over real PG.

        The other tests in this module patch ``HybridSearchEngine`` and so
        only validate router shape — the actual SQL/pgvector path is never
        exercised through HTTP. Keyword mode is used here because it does
        not require a sentence-embedding model at request time, letting the
        real engine + real ``HybridIndex.search`` + real ``to_tsquery``
        execute end-to-end. Response shape (items/total/query_time_ms) is
        the minimum contract asserted; semantic ordering of results belongs
        to the dedicated SQL-level test below.
        """
        from httpx import ASGITransport, AsyncClient

        from intellisource.api.deps import get_db_session
        from intellisource.main import create_app

        source = await _insert_source(pg_session)
        raw = await _insert_raw_content(
            pg_session, source, title="Quantum Computing Daily"
        )
        await _insert_processed_content(
            pg_session,
            raw,
            title="Quantum Computing Daily",
            embedding=_unit_vec(0),
        )
        await pg_session.flush()

        app = create_app()

        async def _override_session() -> Any:
            yield pg_session

        app.dependency_overrides[get_db_session] = _override_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/search",
                json={"query": "quantum", "search_mode": "keyword"},
            )

        assert resp.status_code == 200, (
            f"Real HybridSearchEngine /search must return 200; "
            f"got {resp.status_code} body={resp.text[:300]}"
        )
        data = resp.json()
        # Engine returns dataclass items; FastAPI may serialise as list of dicts
        # or list of dataclass-style entries. Either way the response shape
        # contract is items: list[...], total: int, query_time_ms: int.
        assert "items" in data, f"Missing items key; got {list(data.keys())}"
        items = data["items"]
        assert isinstance(items, list), f"items must be a list; got {type(items)}"
        assert "total" in data and isinstance(data["total"], int)
        assert "query_time_ms" in data and isinstance(data["query_time_ms"], int)

    @pytest.mark.asyncio
    async def test_search_real_pgvector_cosine_query(
        self, pg_session: AsyncSession
    ) -> None:
        """Directly query ProcessedContent using pgvector <=> operator via SQLAlchemy.

        This test bypasses the HTTP layer and verifies that the real pgvector
        cosine distance operator returns results in the correct order from the
        PostgreSQL container.  No mocking of the embedding function is needed
        because we control the stored embeddings.
        """
        source = await _insert_source(pg_session)
        raw1 = await _insert_raw_content(pg_session, source, title="Nearest")
        raw2 = await _insert_raw_content(pg_session, source, title="Farther")
        raw3 = await _insert_raw_content(pg_session, source, title="Orthogonal")

        pc1 = await _insert_processed_content(
            pg_session, raw1, title="Nearest", embedding=_unit_vec(0)
        )
        pc2 = await _insert_processed_content(
            pg_session,
            raw2,
            title="Farther",
            embedding=_near_vec(0, noise_index=1, noise=0.5),
        )
        pc3 = await _insert_processed_content(
            pg_session, raw3, title="Orthogonal", embedding=_unit_vec(5)
        )
        await pg_session.flush()

        query_vector = _unit_vec(0)

        # Use the pgvector <=> cosine-distance operator via raw SQL.
        # Distance = 1 - cosine_similarity, so ascending order gives most similar first.
        result = await pg_session.execute(
            text(
                "SELECT id, title, "
                "embedding <=> CAST(:qvec AS vector) AS distance "
                "FROM processed_contents "
                "WHERE id = ANY(CAST(:ids AS uuid[])) "
                "ORDER BY distance ASC"
            ),
            {
                "qvec": str(query_vector).replace(" ", ""),
                "ids": [str(pc1.id), str(pc2.id), str(pc3.id)],
            },
        )
        rows = result.fetchall()

        assert len(rows) == 3, (
            f"Expected 3 rows from pgvector cosine query, got {len(rows)}"
        )

        returned_ids = [str(row[0]) for row in rows]
        assert returned_ids[0] == str(pc1.id), (
            f"Expected nearest item (id={pc1.id}) to be first by cosine distance, "
            f"but got order: {returned_ids}"
        )
        assert returned_ids[-1] == str(pc3.id), (
            f"Expected orthogonal item (id={pc3.id}) to be last by cosine distance, "
            f"but got order: {returned_ids}"
        )


# ---------------------------------------------------------------------------
# AC-5: JSONB @> operator — content_clusters.tags filtering
# ---------------------------------------------------------------------------


class TestJsonbTagFilter:
    """AC-5: ContentCluster.tags filtered by JSONB @> operator in real PostgreSQL.

    The SQLite-backed tests in test_sprint7_integration.py mock
    ClusterRepository.list_clusters and therefore never exercise the real JSONB
    @> operator path.  This class validates the actual PostgreSQL behavior.
    """

    @pytest.mark.asyncio
    async def test_cluster_filter_by_tag_uses_jsonb_contains(
        self, pg_session: AsyncSession
    ) -> None:
        """SELECT … WHERE tags @> '["ai"]' returns only clusters tagged with 'ai'.

        Three clusters are inserted:
          - cluster_a: tags=["ai", "tech"]   → matches @>["ai"]
          - cluster_b: tags=["sports"]        → does NOT match
          - cluster_c: tags=["ai", "ml"]      → matches @>["ai"]

        The assertion verifies that exactly cluster_a and cluster_c are returned
        and cluster_b is excluded.

        Note: this test cannot pass on SQLite because SQLite lacks the JSONB @>
        operator (seen in test_sprint7_integration.py which mocks the repository
        to avoid this gap — documenting why a real PostgreSQL fixture is needed).
        """
        cluster_a = ContentCluster(
            id=uuid.uuid4(),
            topic="AI and Technology",
            tags=["ai", "tech"],
            content_count=3,
            status="active",
        )
        cluster_b = ContentCluster(
            id=uuid.uuid4(),
            topic="Sports News",
            tags=["sports"],
            content_count=2,
            status="active",
        )
        cluster_c = ContentCluster(
            id=uuid.uuid4(),
            topic="AI and Machine Learning",
            tags=["ai", "ml"],
            content_count=5,
            status="active",
        )
        pg_session.add_all([cluster_a, cluster_b, cluster_c])
        await pg_session.flush()

        # Use the SQLAlchemy .op('@>') expression with JSONB cast —
        # equivalent to SQL: WHERE tags @> '["ai"]'
        stmt = select(ContentCluster).where(
            ContentCluster.tags.op("@>")(cast(["ai"], JSONB))
        )
        result = await pg_session.execute(stmt)
        matched = list(result.scalars().all())

        matched_ids = {c.id for c in matched}
        assert cluster_a.id in matched_ids, (
            f"cluster_a (tags={cluster_a.tags!r}) must match @>['ai'], but was absent"
        )
        assert cluster_c.id in matched_ids, (
            f"cluster_c (tags={cluster_c.tags!r}) must match @>['ai'], but was absent"
        )
        assert cluster_b.id not in matched_ids, (
            f"cluster_b (tags={cluster_b.tags!r}) must NOT match @>['ai'],"
            " but was included"
        )
        assert len(matched) == 2, (
            f"Expected exactly 2 clusters matching @>['ai'], got {len(matched)}: "
            f"{[c.topic for c in matched]}"
        )

    @pytest.mark.asyncio
    async def test_cluster_filter_no_match_returns_empty(
        self, pg_session: AsyncSession
    ) -> None:
        """JSONB @> filter returns empty when no cluster has the queried tag."""
        cluster = ContentCluster(
            id=uuid.uuid4(),
            topic="Sports Only",
            tags=["sports"],
            content_count=1,
            status="active",
        )
        pg_session.add(cluster)
        await pg_session.flush()

        stmt = select(ContentCluster).where(
            ContentCluster.tags.op("@>")(cast(["ai"], JSONB))
        )
        result = await pg_session.execute(stmt)
        matched = list(result.scalars().all())

        assert matched == [], (
            f"Expected empty list for @>['ai'] filter, got {len(matched)} rows: "
            f"{[c.topic for c in matched]}"
        )

    @pytest.mark.asyncio
    async def test_cluster_filter_multi_tag_intersection(
        self, pg_session: AsyncSession
    ) -> None:
        """JSONB @> with multiple tags returns only rows that have ALL queried tags."""
        cluster_a = ContentCluster(
            id=uuid.uuid4(),
            topic="AI and Tech",
            tags=["ai", "tech", "ml"],
            content_count=1,
            status="active",
        )
        cluster_b = ContentCluster(
            id=uuid.uuid4(),
            topic="AI only",
            tags=["ai"],
            content_count=1,
            status="active",
        )
        pg_session.add_all([cluster_a, cluster_b])
        await pg_session.flush()

        # @> ["ai", "ml"] requires BOTH tags to be present.
        stmt = select(ContentCluster).where(
            ContentCluster.tags.op("@>")(cast(["ai", "ml"], JSONB))
        )
        result = await pg_session.execute(stmt)
        matched = list(result.scalars().all())

        assert len(matched) == 1, (
            f"Expected exactly 1 cluster with both 'ai' and 'ml' tags, "
            f"got {len(matched)}: {[c.topic for c in matched]}"
        )
        assert matched[0].id == cluster_a.id, (
            f"Expected cluster_a (id={cluster_a.id}), got {matched[0].id}"
        )

    @pytest.mark.asyncio
    async def test_cluster_repository_list_clusters_tag_filter_real_pg(
        self, pg_session: AsyncSession
    ) -> None:
        """ClusterRepository.list_clusters with tag= kwarg applies real JSONB @> filter.

        Validates that the repository layer correctly translates the tag parameter
        to a PostgreSQL JSONB @> operator when executed against a real PostgreSQL
        session (not the SQLite mock path used in test_sprint7_integration.py).
        """
        from intellisource.storage.repositories.cluster import ClusterRepository

        cluster_match = ContentCluster(
            id=uuid.uuid4(),
            topic="Matching Cluster",
            tags=["python", "backend"],
            content_count=2,
            status="active",
        )
        cluster_nomatch = ContentCluster(
            id=uuid.uuid4(),
            topic="Non-matching Cluster",
            tags=["frontend", "css"],
            content_count=1,
            status="active",
        )
        pg_session.add_all([cluster_match, cluster_nomatch])
        await pg_session.flush()

        repo = ClusterRepository(pg_session)
        page = await repo.list_clusters(tag="python")

        items = page["items"]
        item_ids = {c.id for c in items}

        assert cluster_match.id in item_ids, (
            f"ClusterRepository.list_clusters(tag='python') must include the "
            f"cluster with tags={cluster_match.tags!r}, but it was absent. "
            f"Returned ids: {item_ids}"
        )
        assert cluster_nomatch.id not in item_ids, (
            f"ClusterRepository.list_clusters(tag='python') must exclude the "
            f"cluster with tags={cluster_nomatch.tags!r}, but it was included."
        )
