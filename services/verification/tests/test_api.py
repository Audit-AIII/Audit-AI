"""POST /v1/verify: success, invalid and malformed requests, error mapping, OpenAPI, and
compatibility with the backend's own error handlers (services/api, read-only)."""

import json
import os
import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", message=".*httpx.*", category=DeprecationWarning)
from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from inkloom_verify.api import ENGINE_MODE_HEADER, ENGINE_MODE_VAR, create_dev_app, create_verify_router  # noqa: E402
from inkloom_verify.fake_engine import FAKE_MODEL_ID, FAKE_NOTICE, FakeEngine  # noqa: E402
from inkloom_verify.schemas import (  # noqa: E402
    ErrorCode,
    ReportStatus,
    RetrievalMethod,
    Verdict,
    VerificationReport,
    VerificationRequest,
)
from inkloom_verify.scope import report_violations  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
API_EXAMPLES = EXAMPLES / "api"
BACKEND_SRC = ROOT.parent / "api" / "src"
FOUR_CLAIMS = (
    "The Lumen Bottle keeps drinks cold for up to 24 hours. It is made from 90% recycled steel. "
    "Lumen was founded in 2015. The bottle weighs 340 g."
)


def request_body(**changes) -> dict:
    body = json.loads((EXAMPLES / "verification_request.json").read_text(encoding="utf-8"))
    body.update(changes)
    return body


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_dev_app(FakeEngine()))


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status
    error = response.json()["error"]
    assert set(error) == {"code", "message", "request_id"}
    assert error["code"] == code and error["request_id"]
    return error


# --- Success -----------------------------------------------------------------------------------


def test_verify_returns_a_valid_report_for_the_request(client):
    body = request_body()
    response = client.post("/v1/verify", json=body)
    assert response.status_code == 200
    report = VerificationReport.model_validate(response.json())
    assert report_violations(VerificationRequest.model_validate(body), report) == []
    assert report.reference_set_id == "refset-lumen-launch"


def test_canned_results_are_labelled_and_never_review_free(client):
    response = client.post("/v1/verify", json=request_body())
    report = VerificationReport.model_validate(response.json())
    assert response.headers[ENGINE_MODE_HEADER] == "fake"
    assert (report.provenance.provider, report.provenance.model_id) == ("fake", FAKE_MODEL_ID)
    assert report.provenance.retrieval_method is RetrievalMethod.BM25  # retrieval is real; verdicts are not
    assert all(p.retrieval.method is RetrievalMethod.BM25 for r in report.results for p in r.evidence)
    assert any("no AI verification was performed" in e.message for e in report.errors)
    assert report.status is ReportStatus.PARTIAL and report.score.requires_human_review
    for result in report.results:
        assert (result.model_rationale or result.error.message).startswith(("FAKE ENGINE", FAKE_NOTICE))


def test_every_verdict_shape_is_served(client):
    report = VerificationReport.model_validate(
        client.post("/v1/verify", json=request_body(content={"text": FOUR_CLAIMS})).json()
    )
    assert [r.verdict for r in report.results] == [
        Verdict.SUPPORTED, Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE, Verdict.ERROR,
    ]
    supported, contradicted, unverified, error = report.results
    assert supported.citations and not supported.requires_human_review
    assert contradicted.citations and contradicted.requires_human_review
    assert unverified.citations == [] and error.error.code is ErrorCode.INTERNAL_ERROR


def test_citations_quote_the_retrieved_passages_verbatim(client):
    body = request_body()
    report = VerificationReport.model_validate(client.post("/v1/verify", json=body).json())
    documents = {d.doc_id: d for d in VerificationRequest.model_validate(body).references}
    for result in report.results:
        for citation in result.citations:
            assert citation.matches(documents[citation.doc_id])


def test_a_processing_failure_is_a_report_not_an_http_error(client):
    response = client.post("/v1/verify", json=request_body(content={"text": "--- !!! ---"}))
    assert response.status_code == 200
    report = VerificationReport.model_validate(response.json())
    assert report.status is ReportStatus.FAILED and report.results == []
    assert report.errors[0].code is ErrorCode.PROVIDER_NOT_CONFIGURED


# --- Invalid and malformed requests ------------------------------------------------------------

INVALID = json.loads((EXAMPLES / "invalid" / "cases.json").read_text(encoding="utf-8"))
INVALID_REQUESTS = [c for c in INVALID if c["model"] == "VerificationRequest"]


@pytest.mark.parametrize("case", INVALID_REQUESTS, ids=[c["file"] for c in INVALID_REQUESTS])
def test_invalid_request_fixtures_get_a_safe_422(client, case):
    raw = (EXAMPLES / "invalid" / case["file"]).read_text(encoding="utf-8")
    error = assert_error(client.post("/v1/verify", content=raw, headers={"content-type": "application/json"}), 422, "VALIDATION_ERROR")
    assert error["message"].startswith("invalid request: ")
    for secret in ("../all-tenants", "Lumen Bottle keeps drinks"):
        assert secret not in error["message"]  # locations only, never submitted values


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"{not json", "application/json"),
        (b"", "application/json"),
        (b"[]", "application/json"),
        (b"null", "application/json"),
        (b"request_id=1", "application/x-www-form-urlencoded"),
        (json.dumps({"request_id": 5}).encode(), "application/json"),
    ],
)
def test_malformed_bodies_get_a_safe_422(client, content, content_type):
    assert_error(client.post("/v1/verify", content=content, headers={"content-type": content_type}), 422, "VALIDATION_ERROR")


def test_oversized_bodies_are_refused_before_parsing(client):
    from inkloom_verify.api import MAX_BODY_BYTES

    response = client.post(
        "/v1/verify", content=b"{}", headers={"content-type": "application/json", "content-length": str(MAX_BODY_BYTES + 1)}
    )
    error = assert_error(response, 422, "VALIDATION_ERROR")
    assert "body" in error["message"]


def test_wrong_method_and_unknown_route(client):
    assert client.get("/v1/verify").status_code == 405
    assert client.post("/v1/verifyx", json=request_body()).status_code == 404


# --- Error mapping -----------------------------------------------------------------------------


def app_with(engine, tenant: str | None = None) -> TestClient:
    from inkloom_verify.api import install_dev_error_handlers

    app = FastAPI()
    install_dev_error_handlers(app)
    app.include_router(create_verify_router(engine, authenticated_tenant=(lambda: tenant) if tenant else None))
    return TestClient(app, raise_server_exceptions=False)


def test_tenant_mismatch_is_forbidden():
    assert app_with(FakeEngine(), tenant="tenant-acme").post("/v1/verify", json=request_body()).status_code == 200
    response = app_with(FakeEngine(), tenant="tenant-other").post("/v1/verify", json=request_body())
    assert "match" in assert_error(response, 403, "FORBIDDEN")["message"]


class BrokenEngine:
    mode = "broken"

    def verify(self, request):
        raise RuntimeError(f"secret detail: {request.content.text}")


class ForeignEngine:
    """Returns a valid report for a different request: the endpoint must not pass it on."""

    mode = "foreign"

    def verify(self, request):
        return FakeEngine().verify(request.model_copy(update={"request_id": "req-someone-else"}))


@pytest.mark.parametrize("engine", [BrokenEngine(), ForeignEngine()], ids=["exception", "foreign-report"])
def test_engine_failures_become_a_safe_500(engine):
    response = app_with(engine).post("/v1/verify", json=request_body())
    error = assert_error(response, 500, "INTERNAL_ERROR")
    assert error["message"] == "an internal error occurred" and "Lumen" not in response.text


def test_any_engine_can_replace_the_fake():
    report = json.loads((EXAMPLES / "verification_report.json").read_text(encoding="utf-8"))

    class FixtureEngine:
        mode = "fixture"

        def verify(self, request):
            return VerificationReport.model_validate(report)

    response = app_with(FixtureEngine()).post("/v1/verify", json=request_body())
    assert response.status_code == 200 and response.headers[ENGINE_MODE_HEADER] == "fixture"


# --- OpenAPI and the development app -----------------------------------------------------------


def test_openapi_documents_the_endpoint(client):
    spec = client.get("/openapi.json").json()
    operation = spec["paths"]["/v1/verify"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/VerificationRequest")
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/VerificationReport")
    assert {"403", "422"} <= set(operation["responses"])
    assert client.get("/docs").status_code == 200


def test_dev_app_never_serves_canned_results_by_default(monkeypatch):
    monkeypatch.delenv(ENGINE_MODE_VAR, raising=False)
    with pytest.raises(RuntimeError, match="INKLOOM_ENGINE_MODE=fake"):
        create_dev_app()
    monkeypatch.setenv(ENGINE_MODE_VAR, "live")
    with pytest.raises(RuntimeError):
        create_dev_app()
    monkeypatch.setenv(ENGINE_MODE_VAR, "fake")
    assert TestClient(create_dev_app()).post("/v1/verify", json=request_body()).headers[ENGINE_MODE_HEADER] == "fake"


# --- Compatibility with the backend's real error handling (read-only import) -------------------


@pytest.fixture
def backend_modules():
    sys.path.insert(0, str(BACKEND_SRC))
    try:
        from inkloom_api.errors import install_error_handlers
        from inkloom_api.logging import RequestIdMiddleware
    except ImportError as error:  # pragma: no cover - only if the backend tree is absent
        pytest.skip(f"backend not importable: {error}")
    finally:
        sys.path.remove(str(BACKEND_SRC))
    return install_error_handlers, RequestIdMiddleware


def test_router_mounted_in_the_backends_error_handling(backend_modules):
    install_error_handlers, RequestIdMiddleware = backend_modules
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(create_verify_router(FakeEngine(), authenticated_tenant=lambda: "tenant-acme"))
    client = TestClient(app, raise_server_exceptions=False)

    assert client.post("/v1/verify", json=request_body()).status_code == 200
    invalid = client.post("/v1/verify", json=request_body(content={"text": "   "}))
    error = assert_error(invalid, 422, "VALIDATION_ERROR")
    assert error["request_id"] == invalid.headers.get("x-request-id")
    assert_error(client.post("/v1/verify", json=request_body(tenant_id="tenant-other")), 403, "FORBIDDEN")


def test_dev_handlers_agree_with_the_backends(backend_modules, client):
    """Same inputs, same status and code from the dev app and from the backend's handlers."""
    install_error_handlers, _ = backend_modules
    backend = FastAPI()
    install_error_handlers(backend)
    backend.include_router(create_verify_router(FakeEngine()))
    backend_client = TestClient(backend, raise_server_exceptions=False)
    for raw in (b"{not json", json.dumps(request_body(references=[])).encode(), b"[]"):
        a = client.post("/v1/verify", content=raw, headers={"content-type": "application/json"})
        b = backend_client.post("/v1/verify", content=raw, headers={"content-type": "application/json"})
        assert (a.status_code, a.json()["error"]["code"], a.json()["error"]["message"]) == (
            b.status_code, b.json()["error"]["code"], b.json()["error"]["message"],
        )


# --- Example responses for the frontend and backend --------------------------------------------


def test_api_examples_are_current(client):
    """examples/api/ is generated from these calls. Set INKLOOM_REGENERATE_EXAMPLES=1 to rewrite it."""
    ok = client.post("/v1/verify", json=request_body(content={"text": FOUR_CLAIMS}))
    bad = client.post("/v1/verify", json=request_body(references=[]))
    files = {
        "verify_request.json": json.dumps(request_body(content={"text": FOUR_CLAIMS}), indent=2, ensure_ascii=False),
        "verify_response.fake.json": json.dumps(ok.json(), indent=2, ensure_ascii=False),
        "verify_error_422.json": json.dumps({**bad.json(), "error": {**bad.json()["error"], "request_id": "<request id>"}}, indent=2),
    }
    if os.environ.get("INKLOOM_REGENERATE_EXAMPLES") == "1":
        API_EXAMPLES.mkdir(exist_ok=True)
        for name, text in files.items():
            (API_EXAMPLES / name).write_text(text + "\n", encoding="utf-8", newline="\n")
    for name, text in files.items():
        assert (API_EXAMPLES / name).read_text(encoding="utf-8") == text + "\n", f"{name} is stale"


# --- Real retrieval behind the endpoint (verdicts still canned) -------------------------------


def test_endpoint_evidence_is_retrieved_for_each_claim(client):
    body = request_body(content={"text": "The Lumen Bottle is made from 90% recycled steel."})
    report = VerificationReport.model_validate(client.post("/v1/verify", json=body).json())
    [result] = report.results
    assert any("recycled content" in p.text for p in result.evidence)  # the relevant passage, ranked
    assert [p.retrieval.rank for p in result.evidence] == list(range(1, len(result.evidence) + 1))


def test_endpoint_returns_no_evidence_when_nothing_is_relevant(client):
    body = request_body(content={"text": "Our CEO enjoys mountain biking."})
    [result] = VerificationReport.model_validate(client.post("/v1/verify", json=body).json()).results
    assert result.evidence == [] and result.verdict is Verdict.NOT_ENOUGH_EVIDENCE  # never a canned fact without evidence


def test_endpoint_evidence_comes_only_from_the_requests_reference_set(client):
    other = {"doc_id": "spec-sheet", "text": "Body: aluminium with 10% recycled content."}
    body = request_body(reference_set_id="refset-other", references=[other],
                        content={"text": "The bottle is made from recycled content."})
    report = VerificationReport.model_validate(client.post("/v1/verify", json=body).json())
    assert report.reference_set_id == "refset-other"
    texts = {p.text for r in report.results for p in r.evidence}
    assert texts == {"Body: aluminium with 10% recycled content."}


def test_endpoint_searches_every_document_in_the_set_and_ranks_best_first(client):
    references = [
        {"doc_id": "brand-guide", "text": "Voice: calm and precise. Primary colour: Lumen Teal."},
        {"doc_id": "bottle-sheet", "text": "Lumen Bottle care: hand wash only. The bottle is not dishwasher safe."},
    ]
    body = request_body(references=references, content={"text": "The Lumen Bottle is dishwasher safe and Lumen Teal."})
    [result] = VerificationReport.model_validate(client.post("/v1/verify", json=body).json()).results
    assert {p.doc_id for p in result.evidence} == {"brand-guide", "bottle-sheet"}  # both documents searched
    ranks = [p.retrieval.rank for p in result.evidence]
    scores = [p.retrieval.score for p in result.evidence]
    assert ranks == sorted(ranks) and scores == sorted(scores, reverse=True)
    assert result.evidence[0].doc_id == "bottle-sheet"  # more claim terms: ranked first
