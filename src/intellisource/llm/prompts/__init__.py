"""LLM prompt templates package — public loading interface.

Implementation lives in :mod:`intellisource.llm.prompts.loader`; this module
only re-exports the loading interface. ``_TEMPLATE_DIR`` / ``read_prompt_source``
are re-exported for :mod:`intellisource.llm.prompt_builder` and the prompt
tests that resolve / patch the template directory.
"""

from __future__ import annotations

from intellisource.llm.prompts.loader import _TEMPLATE_DIR as _TEMPLATE_DIR
from intellisource.llm.prompts.loader import PromptMeta as PromptMeta
from intellisource.llm.prompts.loader import load_prompt as load_prompt
from intellisource.llm.prompts.loader import read_prompt_source as read_prompt_source

__all__ = ["PromptMeta", "load_prompt", "read_prompt_source"]
