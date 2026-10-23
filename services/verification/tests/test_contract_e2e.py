"""Phase 6: the public contract end to end, from request parsing to response serialization, plus
the regression checks the Phase 6 audit found missing. Mocked providers only: no API key, no
external calls."""

import ast
import hashlib
import importlib
import json
import sys
import warnings
from pathlib import Path

import jsonschema
import pytest

warnings.filterwarnings("ignore", message=".*httpx.*", category=DeprecationWarning)
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from e2e_support import CONTENT, DOCS, RoutedProvider, careful_model  # noqa: E402
from inkloom_verify.api import create_verify_router, install_dev_error_handlers  # noqa: E402
from inkloom_verify.api_contract import PUBLIC_SCHEMA_VERSION, Report  # noqa: E402
from inkloom_verify.pipeline import PipelineEngine  # noqa: E402
from inkloom_verify.providers.base import MalformedOutputError, ProviderRateLimitError, ProviderTimeoutError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
PUBLIC = ROOT / "examples" / "public"
BACKEND_SRC = ROOT.parent / "api" / "src"
REPORT_SCHEMA = json.loads((SCHEMAS / "public_report.schema.json").read_text(encoding="utf-8"))
SET = "ref_e2e"
LOADER = {SET: [DOCS["pods-fact-sheet"], DOCS["company-facts"]]}


def body(**changes) -> dict:
    return {"request_id": "req_e2e", "content": {"id": "c1", "text": CONTENT}, "reference_set_id": SET} | changes


def client(respond=careful_model, app: FastAPI | None = None, loader=None, **options) -> TestClient:
    if app is None:
        app = FastAPI()
        install_dev_error_handlers(app)
    app.include_router(create_verify_router(PipelineEngine(RoutedProvider(respond)),
                                            reference_set_loader=loader or (lambda t, s: LOADER.get(s)),
                                            authenticated_tenant=lambda: "tenant-e2e", **options))
    return TestClient(app, raise_server_exceptions=False)


def report_of(response) -> Report:
    """A 200 body must be valid JSON Schema output and a valid public Report."""
    assert response.status_code == 200 and response.headers["content-type"] == "application/json"
    data = response.json()
    jsonschema.Draft202012Validator(REPORT_SCHEMA).validate(data)
    return Report.model_validate(data)


def envelope(response, status: int, code: str) -> dict:
    assert response.status_code == status and response.headers["content-type"] == "application/json"
    data = response.json()
    assert set(data) == {"error"}
    assert set(data["error"]) == {"code", "message", "request_id"} | ({"retry_after"} if status == 429 else set())
    assert data["error"]["code"] == code
    return data["error"]


def everywhere(error):
    return lambda request: error


# --- 1-8: the request paths ----------------------------------------------------------------------


def test_1_valid_request():
    report = report_of(client().post("/v1/verify", json=body()))
    assert report.request_id == "req_e2e" and len(report.claims) == 4


def test_2_invalid_input():
    envelope(client().post("/v1/verify", json=body(content={"id": "c1", "text": " "})), 400, "INVALID_INPUT")


def test_3_unknown_reference_set():
    envelope(client().post("/v1/verify", json=body(reference_set_id="ref_missing")), 404, "REFERENCE_SET_NOT_FOUND")


def test_4_invalid_model_output_after_retries():
    def never_parses(request):
        return {"wrong": "shape"} if request.schema_name == "claim_extraction" else careful_model(request)

    provider = RoutedProvider(never_parses)
    app = FastAPI()
    install_dev_error_handlers(app)
    app.include_router(create_verify_router(PipelineEngine(provider), reference_set_loader=lambda t, s: LOADER.get(s),
                                            authenticated_tenant=lambda: "t"))
    envelope(TestClient(app).post("/v1/verify", json=body()), 422, "UNPARSEABLE_MODEL_OUTPUT")
    assert [c.schema_name for c in provider.calls] == ["claim_extraction", "claim_extraction"]  # the call and its one repair


def test_5_provider_rate_limit():
    response = client(everywhere(ProviderRateLimitError("429", retry_after=4))).post("/v1/verify", json=body())
    assert envelope(response, 429, "RATE_LIMITED")["retry_after"] == 4 and response.headers["Retry-After"] == "4"


def test_6_provider_timeout():
    envelope(client(everywhere(ProviderTimeoutError("slow"))).post("/v1/verify", json=body()), 504, "PROVIDER_TIMEOUT")


def test_7_partial_claim_failure():
    report = report_of(client().post("/v1/verify", json=body()))  # careful_model times out on one claim
    failed = [e for e in report.claims if e.verdict.status.value == "ERROR"]
    assert len(failed) == 1 and failed[0].verdict.error_code.value == "PROVIDER_TIMEOUT"
    assert len(report.claims) - len(failed) == 3


def test_8_mixed_report():
    def mixed(request):
        if request.schema_name == "claim_verification" and "€99" in request.user:
            return MalformedOutputError("not JSON")
        return careful_model(request)

    report = report_of(client(mixed).post("/v1/verify", json=body()))
    codes = sorted(e.verdict.error_code.value for e in report.claims if e.verdict.error_code)
    assert codes == ["MALFORMED_MODEL_OUTPUT", "PROVIDER_TIMEOUT"]
    assert {e.verdict.status.value for e in report.claims} == {"SUPPORTED", "NOT_ENOUGH_EVIDENCE", "ERROR"}


# --- 9-12: versions, fixtures, metadata, OpenAPI -------------------------------------------------


def test_9_schema_version_is_one_value_everywhere():
    data = client().post("/v1/verify", json=body()).json()
    found = [data["schema_version"]]
    for entry in data["claims"]:
        found += [entry["claim"]["schema_version"], entry["verdict"]["schema_version"]]
        found += [e["schema_version"] for e in entry["verdict"]["evidence"]]
    assert set(found) == {PUBLIC_SCHEMA_VERSION}
    for name in ("Report", "Claim", "VerdictResult", "Evidence"):  # and the published schema pins it
        definition = REPORT_SCHEMA if name == "Report" else REPORT_SCHEMA["$defs"][name]
        assert definition["properties"]["schema_version"]["const"] == PUBLIC_SCHEMA_VERSION


@pytest.mark.parametrize("name", ["supported.json", "contradicted.json", "not_enough_evidence.json", "error.json",
                                  "mixed_report.json"])
def test_10_every_fixture_validates(name):
    data = json.loads((PUBLIC / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(REPORT_SCHEMA).validate(data)
    Report.model_validate(data, context={"suggest_corrections": True})


def test_11_required_metadata():
    data = client().post("/v1/verify", json=body()).json()
    assert set(data["metadata"]) == {"content_hash", "errors"}
    assert data["metadata"]["content_hash"] == hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
    assert REPORT_SCHEMA["required"] == ["request_id", "claims", "metadata"]
    assert REPORT_SCHEMA["$defs"]["ReportMetadata"]["required"] == ["content_hash"]


def test_12_openapi_has_one_definition_per_public_model():
    spec = client().get("/openapi.json").json()
    components = set(spec["components"]["schemas"])
    assert components == {"Claim", "Correction", "CorrectionOutcome", "ErrorCode", "Evidence", "Report", "ReportClaim",
                          "ReportError", "ReportMetadata", "Span", "VerdictResult", "VerdictStatus", "VerifyContent",
                          "VerifyOptions", "VerifyRequest"}
    assert not any(n.endswith(("-Input", "-Output")) for n in components)  # no split, duplicated definitions
    assert spec["components"]["schemas"]["Report"]["required"] == REPORT_SCHEMA["required"]
    operation = spec["paths"]["/v1/verify"]["post"]
    assert {"200", "400", "404", "409", "422", "429", "503", "504"} <= set(operation["responses"])


# --- Regression checks found missing by the Phase 6 audit ---------------------------------------


def test_member_3_still_finds_every_engine_name_it_imports():
    """Breaking-change guard: every `from inkloom_verify... import X` in services/api must resolve."""
    if not BACKEND_SRC.exists():
        pytest.skip("backend tree absent")
    used, missing = set(), []
    for path in BACKEND_SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("inkloom_verify"):
                module = importlib.import_module(node.module)
                for alias in node.names:
                    used.add(f"{node.module}.{alias.name}")
                    if not hasattr(module, alias.name):
                        missing.append(f"{path.name}: {node.module}.{alias.name}")
    assert used and missing == []


@pytest.fixture
def backend_handlers():
    sys.path.insert(0, str(BACKEND_SRC))
    try:
        from inkloom_api.errors import install_error_handlers
    except ImportError as error:  # pragma: no cover
        pytest.skip(f"backend not importable: {error}")
    finally:
        sys.path.remove(str(BACKEND_SRC))
    return install_error_handlers


def test_an_unexpected_failure_inside_the_backends_app_is_its_safe_500(backend_handlers):
    app = FastAPI()
    backend_handlers(app)

    def failing_loader(tenant, reference_set):
        raise RuntimeError("database password=hunter2")

    response = client(app=app, loader=failing_loader).post("/v1/verify", json=body())
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in response.text and "Traceback" not in response.text


@pytest.mark.parametrize(
    ("respond", "payload"),
    [(careful_model, body()), (careful_model, body(content={"id": "c1", "text": ""})),
     (careful_model, body(reference_set_id="ref_missing")), (everywhere(ProviderRateLimitError("x")), body()),
     (everywhere(ProviderTimeoutError("x")), body()), (everywhere(RuntimeError("bug")), body())],
    ids=["ok", "invalid", "unknown-set", "rate-limit", "timeout", "internal"],
)
def test_every_response_is_a_report_or_the_envelope(respond, payload):
    """No path returns a bare string, an HTML page or FastAPI's default {"detail": ...} body."""
    response = client(respond).post("/v1/verify", json=payload)
    data = response.json()
    assert response.headers["content-type"] == "application/json"
    if response.status_code == 200:
        Report.model_validate(data)
    else:
        assert set(data) == {"error"} and "detail" not in data


def test_offsets_are_code_points_through_the_endpoint():
    text = "🎧 " + CONTENT  # a character outside the Basic Multilingual Plane first
    data = client().post("/v1/verify", json=body(content={"id": "c1", "text": text})).json()
    for entry in data["claims"]:
        span = entry["claim"]["span"]
        assert text[span["start"]:span["end"]] == entry["claim"]["text"]


# --- Known gaps, recorded by the Phase 6 audit (strict: they fail once fixed, so the marker goes) --


@pytest.mark.xfail(strict=True, reason="Phase 6 finding: Starlette routing errors (405/404) bypass the envelope in the "
                                       "dev app and in the backend's handlers; both register FastAPI's HTTPException only")
@pytest.mark.parametrize(("method", "path"), [("get", "/v1/verify"), ("post", "/v1/verify/extra")])
def test_routing_errors_use_the_envelope(method, path):
    data = getattr(client(), method)(path).json()
    assert set(data) == {"error"}


@pytest.mark.xfail(strict=True, reason="Phase 6 finding (Phase 7 item): the body-size limit reads Content-Length only, "
                                       "so a chunked body is read and parsed whatever its size")
def test_a_chunked_body_over_the_size_limit_is_refused():
    from inkloom_verify.api import MAX_BODY_BYTES

    padded = json.dumps(body())[:-1] + " " * (MAX_BODY_BYTES + 1) + "}"  # valid JSON, small content

    def chunks():
        yield padded.encode("utf-8")

    response = client().post("/v1/verify", content=chunks(), headers={"content-type": "application/json"})
    assert response.status_code == 400
