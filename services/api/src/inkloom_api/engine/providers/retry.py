"""Bounded retry-with-backoff for transient provider failures only.

Mirrors `inkloom_verify.providers.openrouter`'s own pattern (PROMPTS.md, "Retries"): a timeout,
rate limit or 5xx is retried a bounded number of times with exponential backoff; anything else
(auth, bad request, malformed output, not configured) is not retryable and propagates on the
first attempt, so `FallbackProvider` can move to the next provider immediately rather than
waiting out retries that can't help.
"""

from __future__ import annotations

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
) -> JsonCompletion:
    attempt = 0
    while True:
        try:
            return call()
        except _TRANSIENT as error:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = backoff_seconds * (2 ** (attempt - 1))
            if isinstance(error, ProviderRateLimitError) and error.retry_after is not None:
                delay = min(max(delay, error.retry_after), _MAX_RETRY_AFTER_SECONDS)
            sleep(delay)
