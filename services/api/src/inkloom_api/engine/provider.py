"""Assembles the provider fallback chain: Gemini Flash, Groq, OpenRouter `:free`, local
Ollama, in that order (docs/backend.md, "Provider adapter, cache and idempotency").

If none of the four are configured, `build_provider()` still returns a usable `FallbackProvider`
— it simply has an empty `configured_providers` list. The caller (pipeline.py) checks that and
falls back to a clearly labelled stub rather than failing the whole route (Phase 3 rule).

Task 8 (confidential routing): when `confidential=True`, the cloud builders are never even in
the list - not skipped at call time, never offered to `FallbackProvider` at all - so there is
no code path by which a confidential source's content could reach Gemini, Groq or OpenRouter.
Only Ollama (local) is tried.
"""

from __future__ import annotations

from collections.abc import Callable

from inkloom_verify.providers.base import LLMProvider
from inkloom_verify.providers.openrouter import OpenRouterProvider

from .providers.fallback import AttemptObserver, FallbackProvider, noop_observer
from .providers.gemini import GeminiProvider
from .providers.groq import GroqProvider
from .providers.ollama import OllamaProvider

_CLOUD_BUILDERS: list[tuple[str, Callable[[], LLMProvider]]] = [
    ("gemini", GeminiProvider.from_env),
    ("groq", GroqProvider.from_env),
    ("openrouter", OpenRouterProvider.from_env),
]
_LOCAL_BUILDERS: list[tuple[str, Callable[[], LLMProvider]]] = [
    ("ollama", OllamaProvider.from_env),
]


def build_provider(
    confidential: bool = False, on_attempt: AttemptObserver = noop_observer
) -> FallbackProvider:
    builders = _LOCAL_BUILDERS if confidential else _CLOUD_BUILDERS + _LOCAL_BUILDERS
    return FallbackProvider(builders, on_attempt=on_attempt)
