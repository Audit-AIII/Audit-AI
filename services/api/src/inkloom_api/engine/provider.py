"""Assembles the Phase 5 provider fallback chain: Gemini Flash, Groq, OpenRouter `:free`, local
Ollama, in that order (member3_backend/phase5_provider_adapter_cache_idempotency.md task 1).

If none of the four are configured, `build_provider()` still returns a usable `FallbackProvider`
— it simply has an empty `configured_providers` list. The caller (pipeline.py) checks that and
falls back to a clearly labelled stub rather than failing the whole route (Phase 3 rule).
"""

from __future__ import annotations

from collections.abc import Callable

from inkloom_verify.providers.base import LLMProvider
from inkloom_verify.providers.openrouter import OpenRouterProvider

from .providers.fallback import AttemptObserver, FallbackProvider, noop_observer
from .providers.gemini import GeminiProvider
from .providers.groq import GroqProvider
from .providers.ollama import OllamaProvider

_BUILDERS: list[tuple[str, Callable[[], LLMProvider]]] = [
    ("gemini", GeminiProvider.from_env),
    ("groq", GroqProvider.from_env),
    ("openrouter", OpenRouterProvider.from_env),
    ("ollama", OllamaProvider.from_env),
]


def build_provider(on_attempt: AttemptObserver = noop_observer) -> FallbackProvider:
    return FallbackProvider(_BUILDERS, on_attempt=on_attempt)
