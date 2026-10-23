"""Bounded retry-with-backoff for transient provider failures only.

Mirrors `inkloom_verify.providers.openrouter`'s own pattern (PROMPTS.md, "Retries"): a timeout,
rate limit or 5xx is retried a bounded number of times with exponential backoff; anything else
(auth, bad request, malformed output, not configured) is not retryable and propagates on the
first attempt, so `FallbackProvider` can move to the next provider immediately rather than
waiting out retries that can't help.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from inkloom_verify.providers.base import (
    JsonCompletion,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_TRANSIENT = (ProviderRateLimitError, ProviderTimeoutError, ProviderUnavailableError)
_MAX_RETRY_AFTER_SECONDS = 20.0


def with_retry(
    call: Callable[[], JsonCompletion],
    *,
    max_retries: int = 2,
    backoff_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> JsonCompletion:
    """Calls ``call``; retries transient failures at most ``max_retries`` times. Each wait is the
    exponential step scaled by a random factor in [0.5, 1) ("equal jitter", so many clients
    don't retry in lockstep), never above ``_MAX_RETRY_AFTER_SECONDS``; a provider's
    Retry-After is honoured when it is longer, up to the same cap."""
    attempt = 0
    while True:
        try:
            return call()
        except _TRANSIENT as error:
            attempt += 1
            if attempt > max_retries:
                raise
            step = backoff_seconds * (2 ** (attempt - 1))
            delay = min(step * (0.5 + jitter() / 2), _MAX_RETRY_AFTER_SECONDS)
            if isinstance(error, ProviderRateLimitError) and error.retry_after is not None:
                delay = min(max(delay, error.retry_after), _MAX_RETRY_AFTER_SECONDS)
            sleep(delay)
