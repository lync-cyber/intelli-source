"""Tests for PromptBuilder.prompt_version + LLMGateway auto-fill (T-069).

Covers:
- AC-T069-1: prompt_version returns SHA-256 first 8 hex chars of template file.
- AC-T069-2: template content change → prompt_version changes.
- AC-T069-3: gateway.complete() auto-fills cache_key_parts.prompt_version
             from PromptBuilder.
- AC-T069-4: missing template file at access time → "unknown".
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.llm.gateway import LLMGateway, LLMResult
from intellisource.llm.prompt_builder import PromptBuilder


@pytest.fixture
def real_template_path() -> Path:
    """Path to the real `extraction.txt` template shipped with the package."""
    from intellisource.llm.prompts import _TEMPLATE_DIR  # noqa: PLC0415

    return _TEMPLATE_DIR / "extraction.txt"


# ----------------------------------------------------------------- AC-T069-1


class TestPromptVersionHash:
    def test_prompt_version_is_first_8_hex_of_sha256(
        self, real_template_path: Path
    ) -> None:
        builder = PromptBuilder(call_type="extraction")
        expected = hashlib.sha256(real_template_path.read_bytes()).hexdigest()[:8]
        assert builder.prompt_version == expected
        assert len(builder.prompt_version) == 8
        assert all(c in "0123456789abcdef" for c in builder.prompt_version)

    def test_prompt_version_is_deterministic(self) -> None:
        b1 = PromptBuilder(call_type="extraction")
        b2 = PromptBuilder(call_type="extraction")
        assert b1.prompt_version == b2.prompt_version

    def test_call_type_property_exposes_constructor_arg(self) -> None:
        builder = PromptBuilder(call_type="extraction")
        assert builder.call_type == "extraction"


# ----------------------------------------------------------------- AC-T069-2


class TestPromptVersionTracksContentChanges:
    def test_content_change_changes_version(self, tmp_path: Path) -> None:
        # Point the template lookup at a temporary directory.
        custom_dir = tmp_path / "templates"
        custom_dir.mkdir()
        tpl = custom_dir / "demo.txt"
        tpl.write_text("hello {name}", encoding="utf-8")

        with (
            patch("intellisource.llm.prompt_builder._TEMPLATE_DIR", custom_dir),
            patch("intellisource.llm.prompts._TEMPLATE_DIR", custom_dir),
        ):
            # Reset lru_cache so the new template is read fresh.
            from intellisource.llm.prompts import _read_template  # noqa: PLC0415

            _read_template.cache_clear()
            v1 = PromptBuilder(call_type="demo").prompt_version

            tpl.write_text("hello {name}, updated body", encoding="utf-8")
            v2 = PromptBuilder(call_type="demo").prompt_version

        assert v1 != v2
        assert len(v1) == len(v2) == 8


# ----------------------------------------------------------------- AC-T069-3


class TestGatewayAutoFillsPromptVersion:
    async def test_gateway_auto_fills_prompt_version_from_builder(self) -> None:
        builder = PromptBuilder(call_type="extraction")
        cache = AsyncMock()
        cache.get.return_value = LLMResult(content="cached", metadata={})

        gateway = LLMGateway(cache=cache)
        cache_key_parts: dict[str, str] = {"content_fingerprint": "fp-123"}

        with patch.object(gateway, "_log_cache_hit", new=AsyncMock()):
            result = await gateway.complete(
                prompt="hi",
                cache_key_parts=cache_key_parts,
                prompt_builder=builder,
            )

        assert result.content == "cached"
        cache.get.assert_awaited_once()
        call_kwargs = cache.get.await_args.kwargs
        assert call_kwargs["prompt_version"] == builder.prompt_version
        assert call_kwargs["call_type"] == "extraction"
        assert call_kwargs["content_fingerprint"] == "fp-123"

    async def test_explicit_prompt_version_wins_over_builder(self) -> None:
        builder = PromptBuilder(call_type="extraction")
        cache = AsyncMock()
        cache.get.return_value = None

        gateway = LLMGateway(cache=cache)
        cache_key_parts: dict[str, str] = {
            "content_fingerprint": "fp",
            "call_type": "extraction",
            "prompt_version": "manual01",
        }

        with patch.object(
            gateway,
            "_call_with_retry",
            new=AsyncMock(
                return_value=MagicMock(
                    choices=[MagicMock(message=MagicMock(content="x"))],
                    usage=MagicMock(prompt_tokens=1, completion_tokens=1),
                    model="m",
                )
            ),
        ):
            await gateway.complete(
                prompt="hi",
                cache_key_parts=cache_key_parts,
                prompt_builder=builder,
            )

        assert cache_key_parts["prompt_version"] == "manual01"


# ----------------------------------------------------------------- AC-T069-4


class TestUnknownVersionWhenTemplateMissing:
    def test_template_deleted_after_init_returns_unknown(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "templates"
        custom_dir.mkdir()
        tpl = custom_dir / "ephemeral.txt"
        tpl.write_text("hello", encoding="utf-8")

        with (
            patch("intellisource.llm.prompt_builder._TEMPLATE_DIR", custom_dir),
            patch("intellisource.llm.prompts._TEMPLATE_DIR", custom_dir),
        ):
            from intellisource.llm.prompts import _read_template  # noqa: PLC0415

            _read_template.cache_clear()
            builder = PromptBuilder(call_type="ephemeral")
            assert builder.prompt_version != "unknown"

            tpl.unlink()
            assert builder.prompt_version == "unknown"
