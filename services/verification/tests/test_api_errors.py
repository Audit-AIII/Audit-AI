"""Every documented error mapping of POST /v1/verify (Phase 3, approved envelope):

    {"error": {"code", "message", "request_id"}}  (+ "retry_after" and a Retry-After header on 429)

400 INVALID_INPUT, 404 REFERENCE_SET_NOT_FOUND, 409 REFERENCE_SET_EMPTY, 422 UNPARSEABLE_MODEL_OUTPUT,
429 RATE_LIMITED, 504 PROVIDER_TIMEOUT, 503 for other run-wide provider failures, 500 INTERNAL_ERROR.
Mocked providers only."""

import warnings

import pytest

warnings.filterwarnings("ignore", message=".*httpx.*", category=DeprecationWarning)
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from e2e_support import CONTENT, DOCS, ERROR_CLAIM, RoutedProvider, careful_model  # noqa: E402
from inkloom_verify.api import create_verify_router, install_dev_error_handlers  # noqa: E402
from inkloom_verify.pipeline import PipelineEngine  # noqa: E402
from inkloom_verify.providers.base import (  # noqa: E402
    MalformedOutputError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderQuotaError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

SET = "ref_brand_2026"
OWNED = {
    ("tenant-acme", SET): [DOCS["pods-fact-sheet"], DOCS["company-facts"]],
    ("tenant-acme", "ref_empty"): [],
}
SECRET = "sk-or-v1-0000SECRET0000 and the draft text"


def body(**changes) -> dict:
    return {
        "request_id": "req_err",
        "content": {"id": "c1", "text": CONTENT},
        "reference_set_id": SET,
    } | changes


def client_for(respond=careful_model, **options) -> TestClient:
    app = FastAPI()
    install_dev_error_handlers(app)
    app.include_router(
        create_verify_router(
            PipelineEngine(RoutedProvider(respond)),
            reference_set_loader=lambda t, s: OWNED.get((t, s)),
            authenticated_tenant=lambda: "tenant-acme",
            **options,
        )
    )
    return TestClient(app, raise_server_exceptions=False)


def everywhere(error: Exception):
    """A provider that fails every call: the run has no results."""
    return lambda request: error


def extraction_never_parses(request):
    if request.schema_name == "claim_extraction":
        return {"wrong": "shape"}  # invalid, and invalid again after the repair attempt
    return careful_model(request)


def error_of(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert set(error) == {"code", "message", "request_id"} | (
        {"retry_after"} if status == 429 else set()
    )
    return error


# --- 400 INVALID_INPUT ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        body(content={"id": "c1", "text": "   "}),  # empty content
        body(content={"id": "c1", "text": ""}),
        body(options={"max_claims": 0}),  # invalid request schema
        {"content": {"id": "c1", "text": CONTENT}, "reference_set_id": SET},  # missing request_id
    ],
    ids=["whitespace", "empty", "schema", "missing-field"],
)
def test_invalid_input_is_400(payload):
    error = error_of(client_for().post("/v1/verify", json=payload), 400, "INVALID_INPUT")
    assert error["message"].startswith("invalid request: ")


def test_excessively_long_content_is_400():
    error = error_of(
        client_for(max_content_chars=30).post("/v1/verify", json=body()), 400, "INVALID_INPUT"
    )
    assert "content.text" in error["message"]


def test_malformed_json_is_400_with_the_callers_request_id_header():
    response = client_for().post(
        "/v1/verify",
        content=b"{not json",
        headers={"content-type": "application/json", "x-request-id": "trace-77"},
    )
    assert error_of(response, 400, "INVALID_INPUT")["request_id"] == "trace-77"


# --- 404 / 409: unknown is not empty --------------------------------------------------------------


def test_unknown_reference_set_is_404():
    error = error_of(
        client_for().post("/v1/verify", json=body(reference_set_id="ref_unknown")),
        404,
        "REFERENCE_SET_NOT_FOUND",
    )
    assert error["request_id"] == "req_err"


def test_empty_reference_set_is_409_not_404():
    error = error_of(
        client_for().post("/v1/verify", json=body(reference_set_id="ref_empty")),
        409,
        "REFERENCE_SET_EMPTY",
    )
    assert error["request_id"] == "req_err"


# --- Runs with no results, by cause ---------------------------------------------------------------


def test_model_output_still_invalid_after_repair_is_422():
    error_of(
        client_for(extraction_never_parses).post("/v1/verify", json=body()),
        422,
        "UNPARSEABLE_MODEL_OUTPUT",
    )


@pytest.mark.parametrize(("provider_says", "expected"), [(7.2, 8), (0, 0), (None, 30)])
def test_rate_limit_is_429_with_retry_after(provider_says, expected):
    response = client_for(
        everywhere(ProviderRateLimitError("429", retry_after=provider_says))
    ).post("/v1/verify", json=body())
    error = error_of(response, 429, "RATE_LIMITED")
    assert error["retry_after"] == expected and response.headers["Retry-After"] == str(expected)


def test_the_default_retry_after_is_configurable():
    response = client_for(everywhere(ProviderRateLimitError("429")), default_retry_after=5).post(
        "/v1/verify", json=body()
    )
    assert error_of(response, 429, "RATE_LIMITED")["retry_after"] == 5


def test_provider_timeout_is_504():
    response = client_for(everywhere(ProviderTimeoutError("no answer in 30s"))).post(
        "/v1/verify", json=body()
    )
    error_of(response, 504, "PROVIDER_TIMEOUT")
    assert "Retry-After" not in response.headers


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ProviderNotConfiguredError("set OPENROUTER_API_KEY"), "PROVIDER_NOT_CONFIGURED"),
        (ProviderQuotaError("402"), "PROVIDER_QUOTA_EXCEEDED"),
        (ProviderError("502"), "PROVIDER_ERROR"),
    ],
)
def test_other_run_wide_provider_failures_are_503_with_the_engines_code(error, code):
    error_of(client_for(everywhere(error)).post("/v1/verify", json=body()), 503, code)


def test_an_unexpected_failure_inside_the_engine_is_500_not_a_provider_error():
    def broken(request):
        raise RuntimeError(
            "bug"
        )  # not a ProviderError: the pipeline fails closed with INTERNAL_ERROR

    error_of(client_for(broken).post("/v1/verify", json=body()), 500, "INTERNAL_ERROR")


# --- The distinctions this phase must keep --------------------------------------------------------


def test_each_cause_keeps_its_own_status_and_code():
    outcomes = {
        "invalid input": client_for().post(
            "/v1/verify", json=body(content={"id": "c1", "text": " "})
        ),
        "unknown set": client_for().post("/v1/verify", json=body(reference_set_id="ref_unknown")),
        "empty set": client_for().post("/v1/verify", json=body(reference_set_id="ref_empty")),
        "invalid model output": client_for(extraction_never_parses).post("/v1/verify", json=body()),
        "rate limit": client_for(everywhere(ProviderRateLimitError("429"))).post(
            "/v1/verify", json=body()
        ),
        "timeout": client_for(everywhere(ProviderTimeoutError("slow"))).post(
            "/v1/verify", json=body()
        ),
        "internal": client_for(lambda r: (_ for _ in ()).throw(RuntimeError("bug"))).post(
            "/v1/verify", json=body()
        ),
    }
    pairs = {name: (r.status_code, r.json()["error"]["code"]) for name, r in outcomes.items()}
    assert len(set(pairs.values())) == len(pairs), pairs


def test_one_claims_failure_stays_inside_a_200_report():
    """Partial failure: a timeout on one claim is that claim's ERROR verdict, not a 504."""
    response = client_for().post(
        "/v1/verify", json=body()
    )  # careful_model times out on ERROR_CLAIM only
    assert response.status_code == 200
    [failed] = [e for e in response.json()["claims"] if e["claim"]["text"] == ERROR_CLAIM]
    assert failed["verdict"]["error_code"] == "PROVIDER_TIMEOUT"


def test_one_claims_unparseable_output_stays_inside_a_200_report():
    def one_bad_claim(request):
        if (
            request.schema_name == "claim_verification"
            and ERROR_CLAIM not in request.user
            and "€99" in request.user
        ):
            return MalformedOutputError("not JSON")
        return careful_model(request)

    response = client_for(one_bad_claim).post("/v1/verify", json=body())
    assert response.status_code == 200
    assert "MALFORMED_MODEL_OUTPUT" in {
        e["verdict"].get("error_code") for e in response.json()["claims"]
    }


@pytest.mark.parametrize(
    "error",
    [
        ProviderRateLimitError(SECRET),
        ProviderTimeoutError(SECRET),
        ProviderError(SECRET),
        ProviderQuotaError(SECRET),
        MalformedOutputError(SECRET),
    ],
    ids=lambda e: type(e).__name__,
)
def test_error_messages_are_fixed_and_never_echo_provider_text(error):
    response = client_for(everywhere(error)).post("/v1/verify", json=body())
    assert response.status_code >= 400
    assert (
        "SECRET" not in response.text
        and "draft text" not in response.text
        and "Traceback" not in response.text
    )


def test_openapi_lists_every_mapping():
    spec = client_for().get("/openapi.json").json()
    assert {"400", "404", "409", "422", "429", "503", "504"} <= set(
        spec["paths"]["/v1/verify"]["post"]["responses"]
    )
