"""The provider interface and its failure behaviour (docs/backend.md, "Provider adapter, cache
and idempotency"). Cache, idempotency and rate limits are tested in their own modules.

1. Provider returns 429: adapter falls back.   -> test_falls_through_on_rate_limit_to_next_provider
2. Timeout -> fallback (bounded retry is retry.py's own job, tested there; this proves
   FallbackProvider treats an exhausted-retry failure the same as any other). -> test_falls_through_on_timeout
3. Invalid JSON: treated as failure.            -> test_malformed_output_falls_through
4. All providers down: failure.                 -> test_all_providers_failing_raises
   (also: none configured at all)               -> test_no_providers_configured_raises_immediately

Hand-written fakes satisfying the `LLMProvider` protocol directly (no network, no SDK mocking,
same style as inkloom_verify's own `ScriptedProvider`) — `FallbackProvider` only depends on that
protocol, so this tests its own chain logic in isolation from any real provider's HTTP code.
"""

from __future__ import annotations

from inkloom_verify.providers.base import (
    JsonCompletion,
    JsonCompletionRequest,
    MalformedOutputError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
import pytest

from inkloom_api.engine.providers.fallback import FallbackProvider

REQUEST = JsonCompletionRequest(
    system="system", user="user", schema_name="test_schema", json_schema={"type": "object"}
)


class _FakeProvider:
    """Answers each call with the next scripted outcome: a dict (success) or an exception."""

    def __init__(self, name: str, *outcomes: dict | Exception) -> None:
        self.name = name
        self._outcomes = list(outcomes)
        self.calls = 0

    def sampling(self) -> dict:
        return {}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return JsonCompletion(data=outcome, model=f"{self.name}:fake-model", attempts=1)


def _unconfigured(name: str):
    def build():
        raise ProviderNotConfiguredError(f"{name} not configured")

    return build


def _attempt_recorder():
    attempts: list[dict] = []
    return attempts, lambda **kwargs: attempts.append(kwargs)


def test_falls_through_on_rate_limit_to_next_provider() -> None:
    first = _FakeProvider("first", ProviderRateLimitError("slow down"))
    second = _FakeProvider("second", {"ok": True})
    attempts, on_attempt = _attempt_recorder()
    provider = FallbackProvider(
        [("first", lambda: first), ("second", lambda: second)], on_attempt=on_attempt
    )

    result = provider.complete_json(REQUEST)

    assert result.data == {"ok": True}
    assert result.model == "second:fake-model"
    assert [a["provider"] for a in attempts] == ["first", "second"]
    assert attempts[0]["status"] == "error"
    assert attempts[0]["error_code"] == "PROVIDER_RATE_LIMITED"
    assert attempts[1]["status"] == "success"


def test_falls_through_on_timeout() -> None:
    first = _FakeProvider("first", ProviderTimeoutError("timed out"))
    second = _FakeProvider("second", {"ok": True})
    provider = FallbackProvider([("first", lambda: first), ("second", lambda: second)])

    result = provider.complete_json(REQUEST)
    assert result.data == {"ok": True}


def test_malformed_output_falls_through() -> None:
    first = _FakeProvider("first", MalformedOutputError("not JSON"))
    second = _FakeProvider("second", {"ok": True})
    provider = FallbackProvider([("first", lambda: first), ("second", lambda: second)])

    result = provider.complete_json(REQUEST)
    assert result.data == {"ok": True}


def test_falls_through_on_account_error_unlike_openrouters_own_model_list() -> None:
    """The specific gap this phase closes: a 403/404-shaped account error from one PROVIDER
    must not stop the chain, even though inkloom_verify.providers.openrouter's OWN internal
    retry across its configured *models* does stop on exactly this error type."""
    from inkloom_verify.providers.base import ProviderAuthError

    first = _FakeProvider("first", ProviderAuthError("403-shaped"))
    second = _FakeProvider("second", {"ok": True})
    provider = FallbackProvider([("first", lambda: first), ("second", lambda: second)])

    result = provider.complete_json(REQUEST)
    assert result.data == {"ok": True}


def test_all_providers_failing_raises() -> None:
    first = _FakeProvider("first", ProviderTimeoutError("timed out"))
    second = _FakeProvider("second", ProviderUnavailableError("down"))
    provider = FallbackProvider([("first", lambda: first), ("second", lambda: second)])

    with pytest.raises(ProviderUnavailableError) as exc_info:
        provider.complete_json(REQUEST)
    message = str(exc_info.value)
    assert "first=" in message and "second=" in message


def test_no_providers_configured_raises_immediately() -> None:
    provider = FallbackProvider(
        [("first", _unconfigured("first")), ("second", _unconfigured("second"))]
    )

    assert provider.configured_providers == []
    with pytest.raises(ProviderUnavailableError) as exc_info:
        provider.complete_json(REQUEST)
    assert "not_configured" in str(exc_info.value)


def test_configured_providers_skips_unconfigured_ones() -> None:
    working = _FakeProvider("working", {"ok": True})
    provider = FallbackProvider(
        [("missing", _unconfigured("missing")), ("working", lambda: working)]
    )

    assert provider.configured_providers == ["working"]
    result = provider.complete_json(REQUEST)
    assert result.data == {"ok": True}
