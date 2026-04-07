"""FingerprintGenerator: stable SHA-256 content fingerprinting."""

from __future__ import annotations

import hashlib
import re


class FingerprintGenerator:
    """Generate stable SHA-256 fingerprints from normalized title + body text."""

    def generate(self, title: str, body_text: str) -> str:
        """Return a SHA-256 hex digest of the normalized title + body_text."""
        normalized = self._normalize(title) + self._normalize(body_text)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize(text: str) -> str:
        """Lowercase, strip, and collapse whitespace."""
        return re.sub(r"\s+", " ", text.strip().lower())
