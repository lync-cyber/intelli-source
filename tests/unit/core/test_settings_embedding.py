"""AC-3: Settings embedding fields — embedding_dimension, api_base, api_key."""

from __future__ import annotations

import pytest

from intellisource.core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> object:
    """Clear the lru_cache before and after each test so env mutations take effect."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestEmbeddingDimensionDefault:
    def test_default_embedding_dimension_is_1024(self) -> None:
        """AC-3: Settings.embedding_dimension defaults to 1024 when no env var set."""
        s = Settings(
            _env_file=None,
            # Pass no IS_EMBEDDING_DIMENSION so the default kicks in
        )
        assert s.embedding_dimension == 1024, (
            f"Expected default embedding_dimension=1024, got {s.embedding_dimension}"
        )


class TestEmbeddingDimensionOverride:
    def test_embedding_dimension_reads_from_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-3: IS_EMBEDDING_DIMENSION=768 reflected in embedding_dimension field."""
        monkeypatch.setenv("IS_EMBEDDING_DIMENSION", "768")
        get_settings.cache_clear()

        s = get_settings()
        assert s.embedding_dimension == 768, (
            f"Expected embedding_dimension=768 from IS_EMBEDDING_DIMENSION=768, "
            f"got {s.embedding_dimension}"
        )


class TestEmbeddingApiBase:
    def test_default_embedding_api_base_is_empty_string(self) -> None:
        """AC-3: embedding_api_base defaults to '' (empty string) when no env var."""
        s = Settings(_env_file=None)
        assert s.embedding_api_base == "", (
            "Expected empty embedding_api_base by default,"
            f" got {s.embedding_api_base!r}"
        )

    def test_embedding_api_base_reads_from_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-3: IS_EMBEDDING_API_BASE is surfaced on Settings.embedding_api_base."""
        monkeypatch.setenv("IS_EMBEDDING_API_BASE", "http://embedding/v1")
        get_settings.cache_clear()

        s = get_settings()
        assert s.embedding_api_base == "http://embedding/v1", (
            "Expected embedding_api_base='http://embedding/v1',"
            f" got {s.embedding_api_base!r}"
        )


class TestEmbeddingApiKey:
    def test_default_embedding_api_key_is_empty_string(self) -> None:
        """AC-3: embedding_api_key defaults to '' when no env var."""
        s = Settings(_env_file=None)
        assert s.embedding_api_key == "", (
            f"Expected empty embedding_api_key by default, got {s.embedding_api_key!r}"
        )

    def test_embedding_api_key_reads_from_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-3: IS_EMBEDDING_API_KEY is surfaced on Settings.embedding_api_key."""
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", "tei-secret-key")
        get_settings.cache_clear()

        s = get_settings()
        assert s.embedding_api_key == "tei-secret-key", (
            f"Expected embedding_api_key='tei-secret-key', got {s.embedding_api_key!r}"
        )
