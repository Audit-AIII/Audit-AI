"""Bounded retry-with-backoff (engine/providers/retry.py) — phase5 task 3: "Retry only 429,
5xx and timeouts, a bounded number of times, then fall through." No DB, no network: a fake
`sleep` makes this instant.
"""

from __future__ import annotations

import pytest
from inkloom_verify.providers.base import (
    JsonCompletion,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

from inkloom_api.engine.providers.retry import with_retry


def test_transient_error_is_retried_then_succeeds() -> None:
    attempts = []
    sleeps = []

    def call() -> JsonCompletion:
        attempts.append(1)
        if len(attempts) < 3:
            raise ProviderTimeoutError("timed out")
        return JsonCompletion(data={"ok": True}, model="m", attempts=1)

    result = with_retry(call, max_retries=2, backoff_seconds=0.01, sleep=sleeps.append)
    assert result.data == {"ok": True}
    assert len(attempts) == 3
    assert len(sleeps) == 2  # one sleep before each retry, none after final success


def test_transient_error_exhausts_retries_and_raises() -> None:
    attempts = []

    def call() -> JsonCompletion:
        attempts.append(1)
        raise ProviderTimeoutError("timed out")

    with pytest.raises(ProviderTimeoutError):
        with_retry(call, max_retries=2, backoff_seconds=0.01, sleep=lambda s: None)
    assert len(attempts) == 3  # initial attempt + 2 retries, then give up


def test_non_transient_error_is_never_retried() -> None:
    """401/403-style errors propagate on the first attempt - retrying the same provider with
    the same bad key can't help, so FallbackProvider should see this immediately."""
    attempts = []

    def call() -> JsonCompletion:
        attempts.append(1)
        raise ProviderAuthError("bad key")

    with pytest.raises(ProviderAuthError):
        with_retry(call, max_retries=2, backoff_seconds=0.01, sleep=lambda s: None)
    assert len(attempts) == 1


def test_rate_limit_retry_after_is_honoured() -> None:
    sleeps = []
    attempts = []

    def call() -> JsonCompletion:
        attempts.append(1)
        if len(attempts) == 1:
            raise ProviderRateLimitError("slow down", retry_after=5.0)
        return JsonCompletion(data={"ok": True}, model="m", attempts=1)

    with_retry(call, max_retries=2, backoff_seconds=0.01, sleep=sleeps.append)
    assert sleeps[0] == 5.0


def test_rate_limit_retry_after_is_capped() -> None:
    sleeps = []
    attempts = []

    def call() -> JsonCompletion:
        attempts.append(1)
        if len(attempts) == 1:
            raise ProviderRateLimitError("slow down", retry_after=999.0)
        return JsonCompletion(data={"ok": True}, model="m", attempts=1)

    with_retry(call, max_retries=2, backoff_seconds=0.01, sleep=sleeps.append)
    assert sleeps[0] == 20.0  # _MAX_RETRY_AFTER_SECONDS
