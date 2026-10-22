"""The provider adapter itself (phase5 task 1): tries each configured provider in a fixed
order, falling through to the next on ANY `ProviderError` — not just the 403/404/429 that
exposed the gap (OpenRouter's `:free` tier rejecting `require_parameters: true`), since a
provider-specific account/config problem is exactly the case where trying a *different*
provider is most likely to help. Stops only once every provider has failed (task 4).

This class itself satisfies `inkloom_verify.providers.base.LLMProvider` (name, sampling,
complete_json), so it is a drop-in replacement for a single provider wherever Member 2's
`ClaimExtractor` / `ClaimVerifier` expect one — no change to their code.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from inkloom_verify.providers.base import (
    JsonCompletion,
    JsonCompletionRequest,
    LLMProvider,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
)


class AttemptObserver(Protocol):
    def __call__(
        self, *, provider: str, model: str | None, status: str, latency_ms: int, error_code: str | None
    ) -> None: ...


def noop_observer(**_kwargs: Any) -> None:
    pass


class FallbackProvider:
    """Built once per review (or reused across requests if nothing about the configured
    providers changes); every `complete_json` call retries the same fixed chain."""

    name = "fallback"

    def __init__(
        self,
        builders: list[tuple[str, Callable[[], LLMProvider]]],
        on_attempt: AttemptObserver = noop_observer,
    ) -> None:
        self._on_attempt = on_attempt
        self._providers: list[tuple[str, LLMProvider]] = []
        self.unconfigured: list[str] = []
        for provider_name, build in builders:
            try:
                self._providers.append((provider_name, build()))
            except ProviderNotConfiguredError:
                self.unconfigured.append(provider_name)

    @property
    def configured_providers(self) -> list[str]:
        return [name for name, _ in self._providers]

    def sampling(self) -> dict[str, Any]:
        return {"fallback_chain": self.configured_providers}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        failures = [f"{name}=not_configured" for name in self.unconfigured]
        for provider_name, provider in self._providers:
            started = time.monotonic()
            try:
                result = provider.complete_json(request)
            except ProviderError as error:
                latency_ms = int((time.monotonic() - started) * 1000)
                failures.append(f"{provider_name}={error.code.value}")
                self._on_attempt(
                    provider=provider_name, model=None, status="error",
                    latency_ms=latency_ms, error_code=error.code.value,
                )
                continue
            latency_ms = int((time.monotonic() - started) * 1000)
            self._on_attempt(
                provider=provider_name, model=result.model, status="success",
                latency_ms=latency_ms, error_code=None,
            )
            return result

        raise ProviderUnavailableError(f"all providers failed: {', '.join(failures)}"[:500])
