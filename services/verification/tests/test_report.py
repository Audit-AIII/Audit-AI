import pytest
from pydantic import ValidationError

from inkloom_verify.schemas import (
    ProcessingError,
    ReportScore,
    ReviewReason,
    Verdict,
    VerificationReport,
)

REQUEST_ERROR = {
    "code": "LIMIT_EXCEEDED",
    "stage": "extraction",
    "message": "Only the first 200 claims were verified.",
    "retryable": False,
}


@pytest.fixture
def report_data(report_data):
    """The example report without its score, so tests can change results freely."""
    report_data.pop("score")
    return report_data


def check(data: dict, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        VerificationReport.model_validate(data)


def test_example_report_round_trips(report_data):
    report = VerificationReport.model_validate(report_data)
    assert VerificationReport.model_validate_json(report.model_dump_json()) == report


def test_verdict_counts(report_data):
    counts = VerificationReport.model_validate(report_data).verdict_counts()
    assert counts == {
        Verdict.SUPPORTED: 1,
        Verdict.CONTRADICTED: 1,
        Verdict.NOT_ENOUGH_EVIDENCE: 1,
        Verdict.ERROR: 0,
    }


def test_completed_rejects_error_verdicts(report_data, error_result):
    report_data["results"][0] = error_result
    check(report_data, "COMPLETED report must not contain")


def test_completed_rejects_request_errors(report_data):
    report_data["errors"] = [REQUEST_ERROR]
    check(report_data, "COMPLETED report must not contain")


def test_partial_with_error_verdict(report_data, error_result):
    report_data.update(status="PARTIAL")
    report_data["results"][0] = error_result
    assert VerificationReport.model_validate(report_data).verdict_counts()[Verdict.ERROR] == 1


def test_partial_with_request_error_only(report_data):
    report_data.update(status="PARTIAL", errors=[REQUEST_ERROR])
    assert VerificationReport.model_validate(report_data).errors[0].code.value == "LIMIT_EXCEEDED"


def test_partial_requires_an_error(report_data):
    report_data["status"] = "PARTIAL"
    check(report_data, "PARTIAL report must contain an ERROR verdict or an error")


def test_partial_requires_results(report_data):
    report_data.update(status="PARTIAL", results=[], errors=[REQUEST_ERROR])
    check(report_data, "use FAILED")


def test_failed_report(report_data):
    report_data.update(status="FAILED", results=[], errors=[REQUEST_ERROR])
    assert VerificationReport.model_validate(report_data).results == []


def test_failed_rejects_results(report_data):
    report_data.update(status="FAILED", errors=[REQUEST_ERROR])
    check(report_data, "FAILED report must contain errors and no results")


def test_failed_requires_errors(report_data):
    report_data.update(status="FAILED", results=[])
    check(report_data, "FAILED report must contain errors and no results")


def test_completed_with_no_claims_is_valid(report_data):
    report_data["results"] = []
    assert VerificationReport.model_validate(report_data).verdict_counts()[Verdict.SUPPORTED] == 0


def test_duplicate_claim_ids_rejected(report_data):
    report_data["results"][1]["claim"]["claim_id"] = "clm_0001"
    check(report_data, "duplicate claim_id: clm_0001")


def test_claim_span_must_fit_content(report_data):
    report_data["content_length"] = report_data["results"][2]["claim"]["source_span"]["end"] - 1
    check(report_data, "exceeds content_length")


def test_evidence_must_come_from_a_listed_reference(report_data):
    report_data["references"][0]["doc_id"] = "some-other-doc"
    check(report_data, "not in references")


def test_evidence_must_come_from_the_listed_reference_version(report_data):
    report_data["references"][0]["text_sha256"] = "0" * 64
    check(report_data, "not in references")


def test_duplicate_reference_descriptors_rejected(report_data):
    report_data["references"].append(dict(report_data["references"][0], text_sha256="1" * 64))
    check(report_data, "duplicate reference doc_id")


@pytest.mark.parametrize("retryable", ["true", 1, None])
def test_error_retryable_is_strict_bool(retryable):
    with pytest.raises(ValidationError):
        ProcessingError.model_validate(dict(REQUEST_ERROR, retryable=retryable))


def test_error_message_bounds():
    ProcessingError.model_validate(dict(REQUEST_ERROR, message="x" * 500))
    for message in ["", "   ", "x" * 501]:
        with pytest.raises(ValidationError):
            ProcessingError.model_validate(dict(REQUEST_ERROR, message=message))


def test_unknown_error_code_rejected():
    with pytest.raises(ValidationError):
        ProcessingError.model_validate(dict(REQUEST_ERROR, code="SOMETHING_ELSE"))


# --- Score -------------------------------------------------------------------------------------


def test_example_score_matches_its_results():
    from conftest import load_example

    data = load_example("verification_report.json")
    report = VerificationReport.model_validate(data)
    assert report.score == ReportScore.compute(report.results, report.errors)
    assert report.score.evidence_coverage.value == pytest.approx(1 / 3)
    assert report.score.review_reasons == [
        ReviewReason.CONTRADICTED_CLAIMS,
        ReviewReason.UNVERIFIED_CLAIMS,
    ]


def test_tampered_score_is_rejected():
    from conftest import load_example

    data = load_example("verification_report.json")
    data["score"]["supported"] = 3
    data["score"]["evidence_coverage"] = {"supported": 3, "checked": 3, "value": 1.0}
    with pytest.raises(ValidationError, match="score does not match"):
        VerificationReport.model_validate(data)
