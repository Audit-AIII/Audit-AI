"""The shared fixtures in examples/: every valid one validates and round-trips, every invalid one
is rejected for its documented reason, and the manifest is truthful about JSON Schema coverage."""

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from inkloom_verify.extraction import describe_validation_error
from inkloom_verify.schemas import (
    ClaimResult,
    ErrorCode,
    ReportStatus,
    Verdict,
    VerificationReport,
    VerificationRequest,
)
from inkloom_verify.scope import report_violations

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
INVALID = EXAMPLES / "invalid"
MODELS = {"VerificationRequest": VerificationRequest, "ClaimResult": ClaimResult, "VerificationReport": VerificationReport}
VALID = {
    "verification_request.json": VerificationRequest,
    "verification_report.json": VerificationReport,
    "verification_report_failed.json": VerificationReport,
    "claim_result_error.json": ClaimResult,
    "end_to_end/request.json": VerificationRequest,
    "end_to_end/report.scripted.json": VerificationReport,
}
CASES = json.loads((INVALID / "cases.json").read_text(encoding="utf-8"))


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


# --- Valid fixtures ----------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "model"), sorted(VALID.items()))
def test_valid_fixture_validates_and_round_trips(name, model):
    instance = model.model_validate(load(name))
    assert model.model_validate_json(instance.model_dump_json()) == instance
    assert model.model_validate(json.loads(instance.model_dump_json(exclude_none=True))) == instance


def test_failed_fixture_shows_a_processing_error_without_results():
    report = VerificationReport.model_validate(load("verification_report_failed.json"))
    assert report.status is ReportStatus.FAILED and report.results == []
    assert [e.code for e in report.errors] == [ErrorCode.PROVIDER_NOT_CONFIGURED]
    assert report.score.requires_human_review and report.score.evidence_coverage.value is None


def test_request_and_reports_agree_on_identity():
    request = VerificationRequest.model_validate(load("verification_request.json"))
    for name in ("verification_report.json", "verification_report_failed.json"):
        assert report_violations(request, VerificationReport.model_validate(load(name))) == []


# --- Invalid fixtures --------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c["file"] for c in CASES])
def test_invalid_fixture_is_rejected_for_its_documented_reason(case):
    payload = json.loads((INVALID / case["file"]).read_text(encoding="utf-8"))
    with pytest.raises(ValidationError) as caught:
        MODELS[case["model"]].model_validate(payload)
    assert case["pydantic_error_contains"] in describe_validation_error(caught.value)


@pytest.mark.parametrize("case", CASES, ids=[c["file"] for c in CASES])
def test_manifest_is_truthful_about_json_schema_coverage(case):
    report_schema = json.loads((ROOT / "schemas" / "verification_report.schema.json").read_text(encoding="utf-8"))
    schema = {
        "VerificationRequest": json.loads((ROOT / "schemas" / "verification_request.schema.json").read_text(encoding="utf-8")),
        "VerificationReport": report_schema,
        "ClaimResult": {"$defs": report_schema["$defs"], "$ref": "#/$defs/ClaimResult"},
    }[case["model"]]
    payload = json.loads((INVALID / case["file"]).read_text(encoding="utf-8"))
    assert (not jsonschema.Draft202012Validator(schema).is_valid(payload)) is case["json_schema_rejects"]


def test_manifest_lists_every_invalid_fixture():
    files = {p.name for p in INVALID.glob("*.json")} - {"cases.json"}
    assert files == {c["file"] for c in CASES}
    assert all(c["model"] in MODELS and c["description"] for c in CASES)


# --- Malformed and empty input -----------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "{", "not json", "[]", "null", '{"request_id": 5}'])
def test_malformed_json_is_rejected(raw):
    with pytest.raises(ValidationError):
        VerificationRequest.model_validate_json(raw)


def test_empty_object_lists_every_missing_required_field():
    with pytest.raises(ValidationError) as caught:
        VerificationRequest.model_validate({})
    missing = {e["loc"][0] for e in caught.value.errors() if e["type"] == "missing"}
    assert missing == {"request_id", "tenant_id", "content", "references"}
    with pytest.raises(ValidationError) as caught:
        VerificationReport.model_validate({})
    missing = {e["loc"][0] for e in caught.value.errors() if e["type"] == "missing"}
    assert missing == {"request_id", "tenant_id", "content_sha256", "content_length", "references", "status", "provenance"}


# --- reference_set_id --------------------------------------------------------------------------


def test_reference_set_id_is_optional_and_opaque():
    data = load("verification_request.json")
    assert VerificationRequest.model_validate(data).reference_set_id == "refset-lumen-launch"
    data.pop("reference_set_id")
    assert VerificationRequest.model_validate(data).reference_set_id is None
    data["reference_set_id"] = "3f2b1c9e-7a44-4d0e-9b1f-2a6c8d0e4f11"  # a UUID fits
    VerificationRequest.model_validate(data)


@pytest.mark.parametrize("value", ["", "has space", "a/b", "../x", "x" * 129, 42])
def test_malformed_reference_set_ids_are_rejected(value):
    data = load("verification_request.json")
    data["reference_set_id"] = value
    with pytest.raises(ValidationError):
        VerificationRequest.model_validate(data)


def test_a_report_must_echo_the_requests_reference_set():
    request = VerificationRequest.model_validate(load("verification_request.json"))
    report = load("verification_report.json")
    report["reference_set_id"] = "refset-other"
    assert "reference_set_id differs from the request" in report_violations(request, VerificationReport.model_validate(report))
    report.pop("reference_set_id")
    assert "reference_set_id differs from the request" in report_violations(request, VerificationReport.model_validate(report))


# --- requires_human_review ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "index", "expected"),
    [("verification_report.json", 0, False), ("verification_report.json", 1, True), ("verification_report.json", 2, True)],
)
def test_review_flag_is_derived_from_the_verdict_when_omitted(fixture, index, expected):
    result = load(fixture)["results"][index]
    result.pop("requires_human_review")
    assert ClaimResult.model_validate(result).requires_human_review is expected


def test_error_results_always_require_review():
    result = load("claim_result_error.json")
    assert ClaimResult.model_validate(result).requires_human_review is True
    result["requires_human_review"] = False
    with pytest.raises(ValidationError, match="false only for SUPPORTED"):
        ClaimResult.model_validate(result)


@pytest.mark.parametrize("value", ["true", 1, None])
def test_review_flag_must_be_a_boolean(value):
    result = load("verification_report.json")["results"][1]
    result["requires_human_review"] = value
    with pytest.raises(ValidationError):
        ClaimResult.model_validate(result)


def test_review_flag_is_always_serialised():
    result = ClaimResult.model_validate({k: v for k, v in load("claim_result_error.json").items() if k != "requires_human_review"})
    assert json.loads(result.model_dump_json(exclude_none=True))["requires_human_review"] is True
    assert result.verdict is Verdict.ERROR
