"""Keyword token parser for subscription match rules.

Parses keyword tokens into (operator, value) tuples for use by
scorer and matcher components.
"""

from __future__ import annotations


def parse_keyword_token(kw: str) -> tuple[str, str]:
    """Parse a keyword token into (operator, value).

    Supported operators:
    - ``+``: required keyword (value follows the ``+``)
    - ``!``: exclude keyword (value follows the ``!``)
    - ``regex``: regex pattern enclosed in ``/pattern/``
    - ``plain``: plain text keyword (no prefix)

    Boundary rules:
    - Empty string returns ``('plain', '')``.
    - ``/pattern`` with no closing slash is treated as plain.
    - ``//`` returns ``('regex', '')`` (empty regex pattern).
    - Mixed prefix ``+!both`` — first character wins: ``('+', '!both')``.
    """
    if not kw:
        return ("plain", "")

    if kw.startswith("+"):
        return ("+", kw[1:])

    if kw.startswith("!"):
        return ("!", kw[1:])

    if kw.startswith("/") and kw.endswith("/") and len(kw) >= 2:
        return ("regex", kw[1:-1])

    return ("plain", kw)
