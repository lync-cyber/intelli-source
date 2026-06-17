"""AC-4: ORM vector column dimensions must be 1024 and reference EMBEDDING_DIM.

Tests verify:
- ProcessedContent.embedding and ContentCluster.centroid have pgvector dim=1024
- Module-level constant EMBEDDING_DIM == 1024
- Both columns' dim equals EMBEDDING_DIM (not a hard-coded literal divergence)
"""

from __future__ import annotations

from intellisource.storage.models import (
    EMBEDDING_DIM,
    ContentCluster,
    ProcessedContent,
)


def _vector_dim(model: type, col_name: str) -> int:
    """Return the pgvector dimension of a mapped column."""
    col = model.__table__.columns[col_name]
    return col.type.dim


class TestEmbeddingDimConstant:
    def test_embedding_dim_constant_equals_1024(self) -> None:
        """AC-4: Module-level EMBEDDING_DIM must be 1024."""
        assert EMBEDDING_DIM == 1024, (
            f"Expected EMBEDDING_DIM == 1024, got {EMBEDDING_DIM}"
        )


class TestProcessedContentEmbeddingDim:
    def test_processed_content_embedding_dim_is_1024(self) -> None:
        """AC-4: ProcessedContent.embedding column must have pgvector dim=1024."""
        dim = _vector_dim(ProcessedContent, "embedding")
        assert dim == 1024, f"Expected ProcessedContent.embedding dim=1024, got {dim}"

    def test_processed_content_embedding_dim_matches_constant(self) -> None:
        """AC-4: ProcessedContent.embedding dim must equal EMBEDDING_DIM (no drift)."""
        dim = _vector_dim(ProcessedContent, "embedding")
        assert dim == EMBEDDING_DIM, (
            f"ProcessedContent.embedding dim={dim}"
            f" diverges from EMBEDDING_DIM={EMBEDDING_DIM}"
        )


class TestContentClusterCentroidDim:
    def test_content_cluster_centroid_dim_is_1024(self) -> None:
        """AC-4: ContentCluster.centroid column must have pgvector dim=1024."""
        dim = _vector_dim(ContentCluster, "centroid")
        assert dim == 1024, f"Expected ContentCluster.centroid dim=1024, got {dim}"

    def test_content_cluster_centroid_dim_matches_constant(self) -> None:
        """AC-4: ContentCluster.centroid dim must equal EMBEDDING_DIM (no drift)."""
        dim = _vector_dim(ContentCluster, "centroid")
        assert dim == EMBEDDING_DIM, (
            f"ContentCluster.centroid dim={dim}"
            f" diverges from EMBEDDING_DIM={EMBEDDING_DIM}"
        )
