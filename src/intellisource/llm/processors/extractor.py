"""LLM structured extraction processor."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from intellisource.llm.fallback import FallbackManager
    from intellisource.llm.gateway import LLMGateway, SchemaEnforcer

logger = logging.getLogger(__name__)


class LLMExtractor:
    """Extracts structured data from text using LLMGateway + SchemaEnforcer."""

    def __init__(
        self,
        gateway: LLMGateway,
        schema_enforcer: SchemaEnforcer,
        fallback_manager: FallbackManager | None = None,
    ) -> None:
        self._gateway = gateway
        self._schema_enforcer = schema_enforcer
        self._fallback_manager = fallback_manager

    async def extract(self, body_text: str) -> dict[str, Any]:
        """Extract structured data from body_text.

        Returns dict with structured_data key on success.
        Falls back to FallbackManager when SchemaEnforcer raises.
        """
        from intellisource.llm.gateway import SchemaValidationError

        result = await self._gateway.complete(prompt=body_text)
        try:
            structured = self._schema_enforcer.validate(result.content)
            return {"structured_data": structured}
        except SchemaValidationError as exc:
            if self._fallback_manager is not None:
                fallback_result = await self._fallback_manager.execute_fallback(
                    task_type="extract",
                    input_data=body_text,
                )
                return {"structured_data": fallback_result}
            logger.warning("schema validation failed, no fallback configured: %s", exc)
            return {"structured_data": None}
