"""Partial failure (Phase 4): one claim's failure stays with that claim. Exercised through
POST /v1/verify, so every response is the public Report. Mocked models only."""

import json
import warnings
from pathlib import Path

import jsonschema
import pytest

warnings.filterwarnings("ignore", message=".*httpx.*", category=DeprecationWarning)
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from e2e_support import (  # noqa: E402
    CONTENT, CONTRADICTED_CLAIM, DOCS, ERROR_CLAIM, SUPPORTED_CLAIM, UNVERIFIED_CLAIM, RoutedProvider, careful_model,
    data_block,
)
from inkloom_verify.api import create_verify_router, install_dev_error_handlers  # noqa: E402
from inkloom_verify.api_contract import Report  # noqa: E402
from inkloom_verify.pipeline import PipelineEngine  # noqa: E402
from inkloom_verify.providers.base import (  # noqa: E402
    MalformedOutputError, ProviderRateLimitError, ProviderTimeoutError,
)

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "public_report.schema.json").read_text(encoding="utf-8"))
BODY = {"request_id": "req_pf", "content": {"id": "c1", "text": CONTENT}, "reference_set_id": "ref_pods"}
CLAIMS = [SUPPORTED_CLAIM, CONTRADICTED_CLAIM, UNVERIFIED_CLAIM, ERROR_CLAIM]


def model(failures: dict[str, object] | None = None, correction_failure: Exception | None = None):
    """careful_model, except: the ERROR claim answers normally unless listed, listed claims fail with
    their exception, and the correction step can fail."""
    failures = failures or {}

    def respond(request):
        if request.schema_name == "claim_verification":
            claim = data_block(request, "verification_input_json")["claim"]
            if claim in failures:
                return failures[claim]
            if claim == ERROR_CLAIM:
                return {"verdict": "NOT_ENOUGH_EVIDENCE", "citations": [], "rationale": "The fact sheet is silent."}
        if request.schema_name == "claim_correction" and correction_failure is not None:
            raise correction_failure
        return careful_model(request)

    return respond


class Raises:
    """A model reply that raises a non-provider exception (a bug), not a ProviderError."""

    def __init__(self, error: Exception):
        self.error = error


def run(respond) -> tuple[int, dict]:
    def wrapped(request):
        reply = respond(request)
        if isinstance(reply, Raises):
            raise reply.error
        return reply

    app = FastAPI()
    install_dev_error_handlers(app)
    loader = lambda t, s: [DOCS["pods-fact-sheet"], DOCS["company-facts"]] if s == "ref_pods" else None  # noqa: E731
    app.include_router(create_verify_router(PipelineEngine(RoutedProvider(wrapped)), reference_set_loader=loader,
                                            authenticated_tenant=lambda: "tenant-pf"))
    response = TestClient(app, raise_server_exceptions=False).post("/v1/verify", json=BODY)
    return response.status_code, response.json()


def valid(data: dict) -> Report:
    """Requirement 7: schema-valid by the model (with the request's options) and by the JSON Schema."""
    jsonschema.Draft202012Validator(SCHEMA).validate(data)
    return Report.model_validate(data, context={"suggest_corrections": True})


def by_text(report: Report) -> dict:
    return {e.claim.text: e for e in report.claims}


BASELINE = None


def baseline() -> Report:
    global BASELINE
    if BASELINE is None:
        status, data = run(model())
        assert status == 200
        BASELINE = valid(data)
    return BASELINE


# --- 1. All claims succeed -------------------------------------------------------------------------


def test_all_claims_succeed():
    report = baseline()
    assert [e.claim.text for e in report.claims] == CLAIMS
    assert all(e.verdict.status.value != "ERROR" and e.verdict.error_code is None for e in report.claims)
    assert report.metadata.errors == []


# --- 2. One claim fails, the others succeed --------------------------------------------------------


def test_one_claim_fails_while_others_succeed():
    status, data = run(model({SUPPORTED_CLAIM: ProviderTimeoutError("slow")}))
    assert status == 200
    claims = by_text(valid(data))
    assert claims[SUPPORTED_CLAIM].verdict.status.value == "ERROR"
    assert claims[SUPPORTED_CLAIM].verdict.error_code.value == "PROVIDER_TIMEOUT"
    assert [claims[t].verdict.status.value for t in CLAIMS[1:]] == ["CONTRADICTED", "NOT_ENOUGH_EVIDENCE", "NOT_ENOUGH_EVIDENCE"]


# --- 3. Several claims fail, each with its own cause -----------------------------------------------


def test_multiple_claims_fail_independently():
    failures = {SUPPORTED_CLAIM: ProviderTimeoutError("slow"), CONTRADICTED_CLAIM: ProviderRateLimitError("429", retry_after=3),
                UNVERIFIED_CLAIM: MalformedOutputError("not JSON")}
    status, data = run(model(failures))
    assert status == 200
    claims = by_text(valid(data))
    assert {t: claims[t].verdict.error_code.value for t in failures} == {
        SUPPORTED_CLAIM: "PROVIDER_TIMEOUT", CONTRADICTED_CLAIM: "PROVIDER_RATE_LIMITED", UNVERIFIED_CLAIM: "MALFORMED_MODEL_OUTPUT"}
    assert claims[ERROR_CLAIM].verdict.status.value == "NOT_ENOUGH_EVIDENCE"  # the one that did not fail


# --- 4. All four statuses in one report ------------------------------------------------------------


def test_a_mixture_of_every_status():
    status, data = run(careful_model)  # the ERROR claim times out
    assert status == 200
    report = valid(data)
    assert {e.verdict.status.value for e in report.claims} == {"SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE", "ERROR"}


# --- 5. One failure does not erase or change other results -----------------------------------------


@pytest.mark.parametrize("failure", [ProviderTimeoutError("slow"), MalformedOutputError("x"), Raises(RuntimeError("bug"))],
                         ids=["timeout", "malformed", "unexpected-exception"])
def test_one_failure_leaves_every_other_result_exactly_as_it_was(failure):
    status, data = run(model({UNVERIFIED_CLAIM: failure}))
    assert status == 200
    failed, ok = by_text(valid(data)), by_text(baseline())
    for text in (SUPPORTED_CLAIM, CONTRADICTED_CLAIM, ERROR_CLAIM):
        assert failed[text] == ok[text]  # verdict, confidence, evidence, correction, review: identical
    assert failed[UNVERIFIED_CLAIM].verdict.status.value == "ERROR"


# --- 6. Failed claims keep their identity ----------------------------------------------------------


def test_failed_claims_keep_their_id_span_text_and_position():
    status, data = run(model({SUPPORTED_CLAIM: ProviderTimeoutError("a"), ERROR_CLAIM: Raises(KeyError("b"))}))
    assert status == 200
    failed, ok = valid(data), baseline()
    assert [e.claim for e in failed.claims] == [e.claim for e in ok.claims]  # ids, spans, text, order
    for entry in failed.claims:
        assert CONTENT[entry.claim.span.start:entry.claim.span.end] == entry.claim.text


# --- 7 and the rest: schema validity, no fabrication, nothing dropped -----------------------------


def test_every_claim_failing_is_still_a_valid_report_not_an_error_response():
    failures = {t: ProviderTimeoutError("slow") for t in CLAIMS}
    status, data = run(model(failures))
    assert status == 200
    report = valid(data)
    assert len(report.claims) == 4 and all(e.verdict.status.value == "ERROR" for e in report.claims)


def test_failed_claims_carry_no_evidence_no_correction_and_need_review():
    status, data = run(model({SUPPORTED_CLAIM: ProviderTimeoutError("a"), CONTRADICTED_CLAIM: Raises(ValueError("b"))}))
    for entry in valid(data).claims:
        if entry.verdict.status.value == "ERROR":
            assert entry.verdict.evidence == [] and entry.verdict.correction is None
            assert entry.verdict.confidence == 0.0 and entry.verdict.needs_human_review


def test_an_unexpected_exception_in_one_claim_is_that_claims_internal_error():
    status, data = run(model({CONTRADICTED_CLAIM: Raises(RuntimeError("secret: " + CONTENT))}))
    assert status == 200
    claims = by_text(valid(data))
    assert claims[CONTRADICTED_CLAIM].verdict.error_code.value == "INTERNAL_ERROR"
    assert claims[SUPPORTED_CLAIM].verdict.status.value == "SUPPORTED"
    assert "secret" not in json.dumps(data)


def test_a_failed_correction_keeps_its_verdict():
    status, data = run(model(correction_failure=RuntimeError("bug in correction")))
    assert status == 200
    contradicted = by_text(valid(data))[CONTRADICTED_CLAIM].verdict
    assert contradicted.status.value == "CONTRADICTED" and contradicted.evidence
    assert contradicted.correction.status.value == "failed" and contradicted.correction.replacement_text is None
    assert contradicted.needs_human_review


def test_no_claim_is_silently_dropped():
    for failures in ({SUPPORTED_CLAIM: ProviderTimeoutError("a")}, {t: Raises(RuntimeError("x")) for t in CLAIMS}):
        status, data = run(model(failures))
        assert status == 200 and [e["claim"]["text"] for e in data["claims"]] == CLAIMS


def test_contamination_is_not_safe_to_continue_past():
    """The exception to partial failure: a result that does not belong to its request fails the
    whole run (500), because the other results can no longer be trusted either."""
    from e2e_support import request
    from inkloom_verify import pipeline
    from inkloom_verify.schemas import ReportStatus

    original = pipeline._report

    def contaminated(*args):
        report = original(*args)
        data = json.loads(report.model_dump_json())
        data["tenant_id"] = "tenant-other"
        return type(report).model_validate(data)

    pipeline._report = contaminated
    try:
        report = pipeline.verify_request(request(), RoutedProvider(model()))
    finally:
        pipeline._report = original
    assert report.status is ReportStatus.FAILED and report.results == []
