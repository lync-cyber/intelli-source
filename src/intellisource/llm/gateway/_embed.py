"""EmbedMixin: text → vector embedding for LLMGateway.

Routes ``task_type='embed'`` via ``ModelRoutingConfig`` so the embedding
model (e.g. ``text-embedding-3-small``) is configured alongside chat
models in ``config/llm_models.yaml``. All failure paths return ``None`` —
callers (EmbeddingProcessor) treat a missing vector as graceful degrade
(``ProcessedContent.embedding`` stays NULL, vector search returns 0 rows
instead of crashing the content-process pipeline).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import litellm

from intellisource.llm.cost_tracker import LLMCallRecord

logger = logging.getLogger(__name__)


class _EmbedMixin:
    """Provides embed() — single-text vector generation."""

    @staticmethod
    async def _aembedding(**kwargs: Any) -> Any:
        """Thin wrapper around litellm.aembedding for testability."""
        return await litellm.aembedding(**kwargs)

    async def embed(self: Any, text: str) -> list[float] | None:
        if not text or not text.strip():
            return None

        try:
            embed_cfg = self._model_routing.get_model("embed")
        except Exception:
            logger.warning("embed task_type not configured in llm_models routing")
            return None

        model = embed_cfg.get("model") if isinstance(embed_cfg, dict) else None
        if not model:
            logger.warning("embed model not resolved from routing config")
            return None

        start = time.monotonic()
        try:
            response = await self._aembedding(model=model, input=text)
        except Exception:
            logger.warning(
                "LLMGateway.embed _aembedding failed for model=%s", model, exc_info=True
            )
            return None

        elapsed_ms = (time.monotonic() - start) * 1000.0

        embedding: list[float] | None
        try:
            embedding = response.data[0].embedding
        except (AttributeError, IndexError, TypeError):
            return None

        if not isinstance(embedding, list) or not embedding:
            return None

        if self._cost_tracker is not None or self._session_factory is not None:
            try:
                response_model = str(getattr(response, "model", model))
            except Exception:
                response_model = model
            try:
                input_tokens = int(getattr(response.usage, "prompt_tokens", 0))
            except (AttributeError, TypeError, ValueError):
                input_tokens = 0
            record = LLMCallRecord(
                model=response_model,
                provider=(
                    response_model.split("/")[0]
                    if isinstance(response_model, str) and "/" in response_model
                    else "unknown"
                ),
                call_type="embed",
                input_tokens=input_tokens,
                output_tokens=0,
                latency_ms=int(elapsed_ms),
                input_length=len(text),
                output_length=len(embedding),
                status="success",
            )
            try:
                await self._emit_call_log(record)
            except Exception:
                logger.warning("emit_call_log failed for embed call", exc_info=True)

        return embedding
