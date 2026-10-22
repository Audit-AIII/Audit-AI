"""Which LLM provider the pipeline uses.

`OpenRouterProvider.from_env()` raises `ProviderNotConfiguredError` when `OPENROUTER_API_KEY` /
`INKLOOM_LLM_MODELS` are not set. Phase 3's rule (member3_backend/phase3_vertical_slice.md task
3): if the engine isn't usable, fall back to a clearly labelled stub rather than failing the
whole route — see `pipeline.STUB_EXPLANATION` for what the stub produces and why.
"""

from __future__ import annotations

import logging

from inkloom_verify.providers.base import LLMProvider, ProviderNotConfiguredError
from inkloom_verify.providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)


def build_provider() -> tuple[LLMProvider | None, str | None]:
    """(provider, None) when configured; (None, safe_reason) otherwise."""
    try:
        return OpenRouterProvider.from_env(), None
    except ProviderNotConfiguredError as error:
        logger.warning("LLM provider not configured, falling back to stub output: %s", error)
        return None, str(error)
