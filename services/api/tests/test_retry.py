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


def test_backoff_is_exponential_jittered_and_capped() -> None:
    """SECURITY.md (whole system): bounded retries with jittered exponential backoff."""
    from inkloom_verify.providers.base import ProviderUnavailableError

    for jitter, expected in (
        (lambda: 0.0, [0.5, 1.0, 2.0, 4.0]),
        (lambda: 0.999999, [1.0, 2.0, 4.0, 8.0]),
    ):
        sleeps: list[float] = []

        def failing():
            raise ProviderUnavailableError("down")

        with pytest.raises(ProviderUnavailableError):
            with_retry(
                failing, max_retries=4, backoff_seconds=1.0, sleep=sleeps.append, jitter=jitter
            )
        assert sleeps == pytest.approx(
            expected, rel=1e-5
        )  # 4 waits for 4 retries, then it gives up
    sleeps = []
    with pytest.raises(ProviderUnavailableError):
        with_retry(
            lambda: (_ for _ in ()).throw(ProviderUnavailableError("down")),
            max_retries=3,
            backoff_seconds=30.0,
            sleep=sleeps.append,
            jitter=lambda: 0.999999,
        )
    assert max(sleeps) <= 20.0  # never above the cap, whatever the step
