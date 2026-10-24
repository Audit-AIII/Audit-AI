"""OpenRouter adapter tests. All HTTP goes through httpx.MockTransport; nothing leaves the machine."""

import json
import logging

import httpx
import pytest

from inkloom_verify.providers.base import (
    JsonCompletionRequest,
    MalformedOutputError,
    ProviderAuthError,
    ProviderNotConfiguredError,
    ProviderQuotaError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from inkloom_verify.providers.openrouter import OpenRouterProvider, OpenRouterSettings
from inkloom_verify.schemas import ErrorCode, PipelineStage
from inkloom_verify.security import RedactingFilter, redact

KEY = "sk-or-v1-TEST-ONLY-NOT-A-REAL-KEY-000000"  # dummy; never a real credential
REQUEST = JsonCompletionRequest(
    system="system prompt",
    user="user content",
    schema_name="claim_extraction",
    json_schema={"type": "object"},
)


def ok(data: dict, model: str = "google/gemini-flash") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(data)}}],
        },
    )


def provider(handler, models=("google/gemini-flash", "meta-llama/llama"), **settings):
    seen: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result = handler(request, len(seen))
        if isinstance(result, Exception):
            raise result
        return result

    sleeps: list[float] = []
    adapter = OpenRouterProvider(
        OpenRouterSettings(api_key=KEY, models=list(models), **settings),
        client=httpx.Client(transport=httpx.MockTransport(transport)),
        sleep=sleeps.append,
        # Deterministic: the full exponential step (jitter is tested on its own).
        jitter=lambda: 1.0,
    )
    return adapter, seen, sleeps


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


# --- Configuration -----------------------------------------------------------------------------


def test_missing_configuration_names_the_variables():
    with pytest.raises(ProviderNotConfiguredError) as caught:
        OpenRouterSettings.from_env({})
    message = str(caught.value)
    assert "OPENROUTER_API_KEY" in message and "INKLOOM_LLM_MODELS" in message
    assert (
        caught.value.to_processing_error(PipelineStage.EXTRACTION).code
        is ErrorCode.PROVIDER_NOT_CONFIGURED
    )


def test_missing_models_only():
    with pytest.raises(ProviderNotConfiguredError, match="set INKLOOM_LLM_MODELS") as caught:
        OpenRouterSettings.from_env({"OPENROUTER_API_KEY": KEY})
    assert "OPENROUTER_API_KEY" not in str(caught.value).split("set ")[1].split(".")[0]


def test_settings_from_env():
    settings = OpenRouterSettings.from_env(
        {
            "OPENROUTER_API_KEY": f"  {KEY} ",
            "INKLOOM_LLM_MODELS": "google/gemini-flash, meta-llama/llama ,",
            "INKLOOM_LLM_TIMEOUT_SECONDS": "12.5",
            "INKLOOM_LLM_SEED": "none",
        }
    )
    assert settings.api_key.get_secret_value() == KEY
    assert settings.models == ["google/gemini-flash", "meta-llama/llama"]
    assert settings.timeout_seconds == 12.5 and settings.seed is None
    assert (settings.temperature, settings.data_collection, settings.structured_output) == (
        0.0,
        "deny",
        "json_schema",
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OPENROUTER_BASE_URL", "http://openrouter.ai/api/v1"),
        ("INKLOOM_LLM_TIMEOUT_SECONDS", "soon"),
        ("INKLOOM_LLM_STRUCTURED_OUTPUT", "xml"),
        ("INKLOOM_LLM_MODELS", "has spaces in it"),
        ("INKLOOM_LLM_DATA_COLLECTION", "maybe"),
    ],
)
def test_invalid_configuration_names_the_variable_not_the_value(name, value):
    env = {"OPENROUTER_API_KEY": KEY, "INKLOOM_LLM_MODELS": "google/gemini-flash", name: value}
    with pytest.raises(ProviderNotConfiguredError) as caught:
        OpenRouterSettings.from_env(env)
    assert name in str(caught.value)
    assert value not in str(caught.value) and KEY not in str(caught.value)


def test_key_is_hidden_in_reprs():
    settings = OpenRouterSettings(api_key=KEY, models=["google/gemini-flash"])
    assert KEY not in repr(settings) and KEY not in str(settings.model_dump())
    assert KEY not in repr(OpenRouterProvider(settings, client=httpx.Client()).sampling())


# --- Request shape -----------------------------------------------------------------------------


def test_request_body_and_headers():
    adapter, seen, _ = provider(lambda r, n: ok({"statements": []}), seed=7)
    completion = adapter.complete_json(REQUEST)
    assert completion.data == {"statements": []}
    assert (completion.model, completion.attempts) == ("google/gemini-flash", 1)
    [request] = seen
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    sent = body(request)
    assert sent["model"] == "google/gemini-flash"
    assert sent["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user content"},
    ]
    assert (sent["temperature"], sent["seed"], sent["max_tokens"]) == (0.0, 7, 4000)
    assert sent["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "claim_extraction", "strict": True, "schema": {"type": "object"}},
    }
    assert sent["provider"] == {"data_collection": "deny", "require_parameters": True}


def test_json_object_mode_and_no_seed():
    adapter, seen, _ = provider(lambda r, n: ok({}), structured_output="json_object", seed=None)
    adapter.complete_json(REQUEST)
    sent = body(seen[0])
    assert sent["response_format"] == {"type": "json_object"} and "seed" not in sent


def test_fenced_json_is_accepted():
    fenced = httpx.Response(
        200,
        json={
            "choices": [{"finish_reason": "stop", "message": {"content": '```json\n{"a": 1}\n```'}}]
        },
    )
    adapter, _, _ = provider(lambda r, n: fenced)
    assert adapter.complete_json(REQUEST).data == {"a": 1}


# --- Retries and fallbacks ---------------------------------------------------------------------


def test_transient_errors_are_retried_with_backoff():
    responses = [httpx.Response(502), httpx.TimeoutException("slow"), ok({"done": True})]
    adapter, seen, sleeps = provider(lambda r, n: responses[n - 1])
    completion = adapter.complete_json(REQUEST)
    assert completion.data == {"done": True} and completion.attempts == 3
    assert sleeps == [1.0, 2.0]
    assert {body(r)["model"] for r in seen} == {"google/gemini-flash"}


def test_falls_back_to_the_next_model_after_retries():
    def handler(request, n):
        return (
            httpx.Response(503)
            if body(request)["model"] == "google/gemini-flash"
            else ok({"x": 1}, "meta-llama/llama")
        )

    adapter, seen, _ = provider(handler, max_retries=1)
    completion = adapter.complete_json(REQUEST)
    assert completion.model == "meta-llama/llama" and completion.attempts == 3
    assert [body(r)["model"] for r in seen] == [
        "google/gemini-flash",
        "google/gemini-flash",
        "meta-llama/llama",
    ]


def test_request_rejection_moves_to_the_next_model_without_retrying():
    def handler(request, n):
        if body(request)["model"] == "google/gemini-flash":
            return httpx.Response(
                400, json={"error": {"code": 400, "message": "response_format not supported"}}
            )
        return ok({"x": 1})

    adapter, seen, sleeps = provider(handler)
    adapter.complete_json(REQUEST)
    assert len(seen) == 2 and sleeps == []


def test_rate_limit_honours_retry_after_with_a_cap():
    responses = [
        httpx.Response(429, headers={"retry-after": "3"}),
        httpx.Response(429, headers={"retry-after": "999"}),
        ok({}),
    ]
    adapter, _, sleeps = provider(lambda r, n: responses[n - 1])
    adapter.complete_json(REQUEST)
    assert sleeps == [3.0, 20.0]


def test_last_error_is_raised_when_every_model_fails():
    adapter, seen, _ = provider(lambda r, n: httpx.Response(429), max_retries=1)
    with pytest.raises(ProviderRateLimitError) as caught:
        adapter.complete_json(REQUEST)
    assert len(seen) == 4
    assert caught.value.to_processing_error(PipelineStage.EXTRACTION).retryable is True


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, ProviderAuthError), (402, ProviderQuotaError), (403, ProviderAuthError)],
)
def test_account_errors_stop_immediately(status, error):
    adapter, seen, _ = provider(
        lambda r, n: httpx.Response(status, json={"error": {"code": status, "message": "nope"}})
    )
    with pytest.raises(error):
        adapter.complete_json(REQUEST)
    assert len(seen) == 1


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(408), ProviderTimeoutError),
        (
            httpx.Response(404, json={"error": {"code": 404, "message": "no such model"}}),
            ProviderRequestError,
        ),
        (httpx.Response(500, text="<html>oops</html>"), ProviderUnavailableError),
        (
            httpx.Response(200, json={"error": {"code": 502, "message": "upstream died"}}),
            ProviderUnavailableError,
        ),
        (
            httpx.Response(200, json={"error": {"code": 429, "message": "slow down"}}),
            ProviderRateLimitError,
        ),
        (httpx.Response(200, text="not json"), ProviderUnavailableError),
        (httpx.Response(200, json={"choices": []}), ProviderUnavailableError),
        (
            httpx.Response(
                200, json={"choices": [{"finish_reason": "error", "message": {"content": "{}"}}]}
            ),
            ProviderUnavailableError,
        ),
        (
            httpx.Response(
                200,
                json={"choices": [{"finish_reason": "length", "message": {"content": '{"a":'}}]},
            ),
            MalformedOutputError,
        ),
        (
            httpx.Response(
                200, json={"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}
            ),
            MalformedOutputError,
        ),
        (
            httpx.Response(
                200,
                json={
                    "choices": [
                        {"finish_reason": "stop", "message": {"content": "Sure! Here it is"}}
                    ]
                },
            ),
            MalformedOutputError,
        ),
        (
            httpx.Response(
                200, json={"choices": [{"finish_reason": "stop", "message": {"content": "[1, 2]"}}]}
            ),
            MalformedOutputError,
        ),
    ],
)
def test_error_mapping(response, error):
    adapter, _, _ = provider(lambda r, n: response, models=("google/gemini-flash",), max_retries=0)
    with pytest.raises(error):
        adapter.complete_json(REQUEST)


def test_network_failure():
    adapter, _, _ = provider(
        lambda r, n: httpx.ConnectError("refused"), models=("google/gemini-flash",), max_retries=0
    )
    with pytest.raises(ProviderUnavailableError, match="could not reach OpenRouter"):
        adapter.complete_json(REQUEST)


# --- Secrets -----------------------------------------------------------------------------------


def test_key_never_appears_in_errors_or_logs(caplog):
    echo = httpx.Response(401, json={"error": {"code": 401, "message": f"invalid key {KEY}"}})
    adapter, _, _ = provider(lambda r, n: echo)
    caplog.set_level(logging.DEBUG, logger="inkloom_verify.providers.openrouter")
    with pytest.raises(ProviderAuthError) as caught:
        adapter.complete_json(REQUEST)
    assert KEY not in str(caught.value)
    assert KEY not in caught.value.to_processing_error(PipelineStage.EXTRACTION).message
    logging.getLogger("inkloom_verify.providers.openrouter").warning("leak attempt %s", KEY)
    assert KEY not in caplog.text and "[REDACTED]" in caplog.text


def test_content_is_not_logged(caplog):
    adapter, _, _ = provider(lambda r, n: ok({}))
    caplog.set_level(logging.DEBUG)
    adapter.complete_json(REQUEST.model_copy(update={"user": "confidential launch plan"}))
    assert "confidential launch plan" not in caplog.text


def test_redact():
    assert redact(f"Authorization: Bearer {KEY}") == "Authorization: Bearer [REDACTED]"
    assert redact(f"key={KEY}") == "key=[REDACTED]"
    assert redact("value s3cret here", "s3cret") == "value [REDACTED] here"
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "token %s", (KEY,), None)
    RedactingFilter().filter(record)
    assert record.getMessage() == "token [REDACTED]"


def test_backoff_is_jittered_within_half_to_full_step_and_capped():
    """SECURITY.md: bounded retries with jittered exponential backoff (never synchronised retries)."""
    for jitter, expected in ((lambda: 0.0, [0.5, 1.0]), (lambda: 1.0, [1.0, 2.0])):
        responses = [httpx.Response(502), httpx.Response(502), ok({"done": True})]
        sleeps: list[float] = []
        adapter = OpenRouterProvider(
            OpenRouterSettings(api_key=KEY, models=["google/gemini-flash"]),
            client=httpx.Client(
                transport=httpx.MockTransport(lambda r, responses=responses: responses.pop(0))
            ),
            sleep=sleeps.append,
            jitter=jitter,
        )
        adapter.complete_json(REQUEST)
        assert sleeps == expected
    adapter = OpenRouterProvider(
        OpenRouterSettings(api_key=KEY, models=["a/b"], backoff_seconds=30),
        sleep=lambda s: None,
        jitter=lambda: 1.0,
    )
    assert adapter._delay(ProviderUnavailableError("x"), 3) == 20.0  # capped


# --- require_parameters 404: fall back to json_object on the same model (Fix Plan item 8) ---------

NO_ENDPOINTS = httpx.Response(
    404,
    json={
        "error": {
            "code": 404,
            "message": "No endpoints found that can handle the requested parameters.",
        }
    },
)


def test_no_endpoints_for_json_schema_retries_the_same_model_in_json_object_mode():
    def handler(request, n):
        sent = body(request)
        if sent["response_format"]["type"] == "json_schema":
            return NO_ENDPOINTS
        return ok({"x": 1}, model=sent["model"])

    adapter, seen, sleeps = provider(handler)
    result = adapter.complete_json(REQUEST)
    sent = [body(r) for r in seen]
    assert [(s["model"], s["response_format"]["type"]) for s in sent] == [
        ("google/gemini-flash", "json_schema"),
        ("google/gemini-flash", "json_object"),
    ]
    assert (
        result.data == {"x": 1} and result.model == "google/gemini-flash" and result.attempts == 2
    )
    assert sleeps == []  # no backoff: it is a different request, not a retry of a transient failure
    assert all(
        s["provider"] == {"data_collection": "deny", "require_parameters": True} for s in sent
    )  # privacy kept


def test_no_endpoints_even_for_json_object_moves_to_the_next_model():
    def handler(request, n):
        sent = body(request)
        if sent["model"] == "google/gemini-flash":
            return NO_ENDPOINTS
        return ok({"x": 1}, model=sent["model"])

    adapter, seen, _ = provider(handler)
    result = adapter.complete_json(REQUEST)
    assert [(body(r)["model"], body(r)["response_format"]["type"]) for r in seen] == [
        ("google/gemini-flash", "json_schema"),
        ("google/gemini-flash", "json_object"),
        ("meta-llama/llama", "json_schema"),
    ]
    assert result.model == "meta-llama/llama"


def test_an_unknown_model_404_does_not_trigger_the_fallback():
    def handler(request, n):
        if body(request)["model"] == "google/gemini-flash":
            return httpx.Response(404, json={"error": {"code": 404, "message": "no such model"}})
        return ok({"x": 1})

    adapter, seen, _ = provider(handler)
    adapter.complete_json(REQUEST)
    assert [body(r)["response_format"]["type"] for r in seen] == [
        "json_schema",
        "json_schema",
    ]  # straight to model 2


def test_in_json_object_mode_a_no_endpoints_404_is_not_retried():
    def handler(request, n):
        return NO_ENDPOINTS

    adapter, seen, _ = provider(handler, structured_output="json_object")
    with pytest.raises(ProviderRequestError) as info:
        adapter.complete_json(REQUEST)
    assert len(seen) == 2  # one call per model, no extra fallback
    assert "No endpoints" not in str(info.value)  # the provider's text is never echoed


# --- INKLOOM_LLM_MODELS format (comma-separated ids; no JSON, quotes or mappings) ----------------

NEMOTRON = "nvidia/nemotron-3.5-super-vl:free"


def test_the_requested_model_id_is_accepted_and_sent_unchanged():
    settings = OpenRouterSettings.from_env(
        {"OPENROUTER_API_KEY": KEY, "INKLOOM_LLM_MODELS": NEMOTRON}
    )
    assert settings.models == [NEMOTRON]
    adapter, seen, _ = provider(lambda r, n: ok({"x": 1}, model=NEMOTRON), models=(NEMOTRON,))
    assert adapter.complete_json(REQUEST).model == NEMOTRON
    assert body(seen[0])["model"] == NEMOTRON  # the id goes to OpenRouter exactly as configured


def test_several_models_keep_their_order_and_spaces_after_commas_are_fine():
    value = f"{NEMOTRON}, meta-llama/llama-3.3-70b-instruct:free ,google/gemini-flash"
    settings = OpenRouterSettings.from_env({"OPENROUTER_API_KEY": KEY, "INKLOOM_LLM_MODELS": value})
    assert settings.models == [
        NEMOTRON,
        "meta-llama/llama-3.3-70b-instruct:free",
        "google/gemini-flash",
    ]


@pytest.mark.parametrize(
    ("value", "hint"),
    [
        (f'"{NEMOTRON}"', "quote characters"),  # cmd: set INKLOOM_LLM_MODELS="..." keeps the quotes
        (f"'{NEMOTRON}'", "quote characters"),
        (f'["{NEMOTRON}"]', "brackets"),  # JSON list
        (f'{{"verifier": "{NEMOTRON}"}}', "brackets"),  # JSON mapping
        (f"verifier={NEMOTRON}", "'='"),
        (f"{NEMOTRON};google/gemini-flash", "other than commas"),
        (f"{NEMOTRON} google/gemini-flash", "other than commas"),
        (f"https://openrouter.ai/{NEMOTRON}", "URL"),
        (",".join([NEMOTRON] * 6), "6 models"),
    ],
)
def test_wrong_formats_are_refused_with_the_expected_format_and_a_hint(value, hint):
    with pytest.raises(ProviderNotConfiguredError) as caught:
        OpenRouterSettings.from_env({"OPENROUTER_API_KEY": KEY, "INKLOOM_LLM_MODELS": value})
    message = str(caught.value)
    assert (
        "invalid INKLOOM_LLM_MODELS" in message
        and "comma-separated list of 1 to 5 OpenRouter model ids" in message
    )
    assert hint in message
    assert value not in message and KEY not in message


def test_a_key_pasted_into_the_models_variable_is_never_echoed():
    with pytest.raises(ProviderNotConfiguredError) as caught:
        OpenRouterSettings.from_env({"OPENROUTER_API_KEY": KEY, "INKLOOM_LLM_MODELS": f'"{KEY}"'})
    assert KEY not in str(caught.value)


@pytest.mark.parametrize("value", ["", "   ", ",", " , "])
def test_empty_or_blank_models_are_missing_or_invalid_never_accepted(value):
    with pytest.raises(ProviderNotConfiguredError, match="INKLOOM_LLM_MODELS"):
        OpenRouterSettings.from_env({"OPENROUTER_API_KEY": KEY, "INKLOOM_LLM_MODELS": value})


def test_model_ids_need_one_provider_slash_and_at_most_one_variant():
    for bad in ("gemini-flash", "a//b", "a/b/c", "a/b:free:extra", "/model", "provider/"):
        with pytest.raises(ValueError):
            OpenRouterSettings(api_key=KEY, models=[bad])
    for good in ("a/b", "openrouter/auto", NEMOTRON, "meta-llama/llama-3.3-70b-instruct:free"):
        assert OpenRouterSettings(api_key=KEY, models=[good]).models == [good]


# --- Data-policy 404 (seen live 2026-10-24 with nvidia/nemotron-3.5-super-vl:free) ---------------

DATA_POLICY_404 = httpx.Response(
    404,
    json={
        "error": {
            "code": 404,
            "message": (
                "No endpoints found matching your data policy (Free model training). Configure: https://openrouter.ai/settings/privacy"
            ),
        }
    },
)


def test_a_data_policy_404_is_not_mistaken_for_unsupported_parameters_and_gets_no_fallback():
    adapter, seen, sleeps = provider(lambda r, n: DATA_POLICY_404, models=(NEMOTRON,))
    with pytest.raises(ProviderRequestError) as info:
        adapter.complete_json(REQUEST)
    assert (
        len(seen) == 1 and sleeps == []
    )  # no json_object retry: the mode cannot change the data policy
    assert (
        body(seen[0])["provider"]["data_collection"] == "deny"
    )  # the privacy setting is never relaxed
    message = str(info.value)
    assert "data policy" in message and "INKLOOM_LLM_DATA_COLLECTION=deny" in message
    assert "Free model training" not in message  # the provider's own text is not echoed


def test_a_data_policy_404_moves_on_to_the_next_model():
    def handler(request, n):
        return (
            DATA_POLICY_404
            if body(request)["model"] == NEMOTRON
            else ok({"x": 1}, model="google/gemini-flash")
        )

    adapter, seen, _ = provider(handler, models=(NEMOTRON, "google/gemini-flash"))
    assert adapter.complete_json(REQUEST).model == "google/gemini-flash"
    assert [body(r)["model"] for r in seen] == [NEMOTRON, "google/gemini-flash"]
