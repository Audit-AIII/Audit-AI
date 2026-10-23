"""The public API contract (api_contract.py): Claim, Passage, Evidence, Verdict and Report, the
approved decisions, and the mapping from the engine's internal report. Mocked data only."""

import json
import math
import os
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from inkloom_verify.api_contract import (
    CONFIDENCE,
    PUBLIC_SCHEMA_VERSION,
    Claim,
    Correction,
    Evidence,
    NotRepresentable,
    Passage,
    Report,
    VerdictResult,
    to_public_passage,
    to_public_report,
)
from inkloom_verify.schemas import EvidenceStrength, VerificationReport

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
HASH = "a" * 64


def evidence(**changes) -> dict:
    return {"doc_id": "pods-fact-sheet", "location": {"start": 10, "end": 21}, "quote": "Price: €129"} | changes


def verdict(**changes) -> dict:
    return {"status": "SUPPORTED", "confidence": 1.0, "evidence": [evidence()], "needs_human_review": False} | changes


def proposed() -> dict:
    return {"status": "proposed", "span": {"start": 16, "end": 19}, "original_text": "€99", "replacement_text": "€129",
            "evidence": [evidence()]}


def report(*verdicts: dict) -> dict:
    claims = [{"claim": {"claim_id": f"clm_{i:04d}", "text": "Lumen Pods cost €99.", "span": {"start": 0, "end": 20}},
               "verdict": v} for i, v in enumerate(verdicts, start=1)]
    return {"request_id": "req-1", "claims": claims, "metadata": {"content_hash": HASH}}


# --- Valid models ---------------------------------------------------------------------------------


def test_valid_models_and_their_schema_version():
    claim = Claim(claim_id="clm_0001", text="Lumen Pods cost €99.", span={"start": 0, "end": 20})
    passage = Passage(doc_id="pods-fact-sheet", location={"start": 0, "end": 11}, text="Price: €129", score=2.5)
    item = Evidence.model_validate(evidence())
    result = VerdictResult.model_validate(verdict())
    full = Report.model_validate(report(verdict()))
    for model in (claim, passage, item, result, full):
        assert model.schema_version == PUBLIC_SCHEMA_VERSION
    assert json.loads(full.model_dump_json())["metadata"] == {"content_hash": HASH, "errors": [], "prompt_versions": {}}


def test_another_schema_version_is_refused():
    with pytest.raises(ValidationError, match="schema_version"):
        VerdictResult.model_validate(verdict(schema_version="9.9.9"))


def test_unknown_fields_are_refused():
    with pytest.raises(ValidationError, match="extra"):
        VerdictResult.model_validate(verdict(probability=0.9))


# --- Statuses and confidence ----------------------------------------------------------------------


@pytest.mark.parametrize("status", ["PROBABLY", "supported", "", "APPROVED", None, 1])
def test_invalid_statuses(status):
    with pytest.raises(ValidationError):
        VerdictResult.model_validate(verdict(status=status))


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2, math.nan, math.inf, -math.inf, "high", None])
def test_invalid_confidence(confidence):
    with pytest.raises(ValidationError):
        VerdictResult.model_validate(verdict(confidence=confidence))


@pytest.mark.parametrize("confidence", [0, 0.0, 0.33, 0.67, 1, 1.0])
def test_confidence_at_and_within_the_bounds(confidence):
    # needs_human_review=True isolates the bounds from the low-confidence review rule (tested below)
    assert VerdictResult.model_validate(verdict(confidence=confidence, needs_human_review=True)).confidence == confidence


def test_confidence_is_the_approved_fixed_map_of_evidence_strength():
    assert CONFIDENCE == {EvidenceStrength.NONE: 0.0, EvidenceStrength.WEAK: 0.33,
                          EvidenceStrength.MODERATE: 0.67, EvidenceStrength.STRONG: 1.0}


# --- Spans and locations --------------------------------------------------------------------------


@pytest.mark.parametrize("span", [{"start": -1, "end": 5}, {"start": 5, "end": 5}, {"start": 6, "end": 5},
                                  {"start": "0", "end": 5}, {"start": 0.0, "end": 5}, {"start": 0}])
def test_invalid_spans(span):
    with pytest.raises(ValidationError):
        Claim(claim_id="clm_0001", text="Lumen", span=span)
    with pytest.raises(ValidationError):
        Evidence.model_validate(evidence(location=span, quote="Lumen"))


def test_text_must_fill_its_span():
    with pytest.raises(ValidationError, match="claim text length"):
        Claim(claim_id="clm_0001", text="Lumen Pods", span={"start": 0, "end": 4})
    with pytest.raises(ValidationError, match="quote length"):
        Evidence.model_validate(evidence(quote="Price"))
    with pytest.raises(ValidationError, match="passage text length"):
        Passage(doc_id="d", location={"start": 0, "end": 3}, text="Price", score=1.0)


# --- Evidence requirements ------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["SUPPORTED", "CONTRADICTED"])
def test_definite_verdicts_require_evidence(status):
    with pytest.raises(ValidationError, match="requires at least one evidence item"):
        VerdictResult.model_validate(verdict(status=status, evidence=[], needs_human_review=True))


def test_not_enough_evidence_needs_no_evidence():
    result = VerdictResult.model_validate(verdict(status="NOT_ENOUGH_EVIDENCE", confidence=0.0, evidence=[], needs_human_review=True))
    assert result.evidence == []


def test_error_needs_an_error_code_and_nothing_else_has_one():
    with pytest.raises(ValidationError, match="error_code"):
        VerdictResult.model_validate(verdict(status="ERROR", confidence=0.0, evidence=[], needs_human_review=True))
    with pytest.raises(ValidationError, match="error_code"):
        VerdictResult.model_validate(verdict(error_code="PROVIDER_TIMEOUT"))
    with pytest.raises(ValidationError):
        VerdictResult.model_validate(verdict(status="ERROR", evidence=[], needs_human_review=True, error_code="MADE_UP"))
    ok = VerdictResult.model_validate(verdict(status="ERROR", confidence=0.0, evidence=[], needs_human_review=True,
                                              error_code="PROVIDER_TIMEOUT"))
    assert ok.error_code.value == "PROVIDER_TIMEOUT"


def test_only_supported_may_skip_human_review():
    for status, extra in (("CONTRADICTED", {}), ("NOT_ENOUGH_EVIDENCE", {"evidence": []}),
                          ("ERROR", {"evidence": [], "error_code": "INTERNAL_ERROR"})):
        with pytest.raises(ValidationError, match="needs human review"):
            VerdictResult.model_validate(verdict(status=status, needs_human_review=False, **extra))


# --- Correction requirements (suggest_corrections is a request option) ---------------------------


def contradicted(correction=None) -> dict:
    data = verdict(status="CONTRADICTED", confidence=0.67, needs_human_review=True)
    if correction is not None:
        data["correction"] = correction
    return data


def test_contradicted_needs_a_correction_outcome_when_corrections_are_requested():
    with pytest.raises(ValidationError, match="needs a correction outcome"):
        Report.model_validate(report(contradicted()), context={"suggest_corrections": True})
    with pytest.raises(ValidationError, match="needs a correction outcome"):
        Report.model_validate(report(contradicted()))  # the default is true
    Report.model_validate(report(contradicted(proposed())), context={"suggest_corrections": True})


@pytest.mark.parametrize("outcome", ["needs_human_review", "failed"])
def test_no_safe_correction_is_an_explicit_outcome_without_a_replacement(outcome):
    Report.model_validate(report(contradicted({"status": outcome})))
    with pytest.raises(ValidationError, match="only a proposed correction"):
        Correction.model_validate({"status": outcome, "replacement_text": "€129"})


def test_no_correction_may_be_returned_when_none_was_requested():
    with pytest.raises(ValidationError, match="no correction may be returned"):
        Report.model_validate(report(contradicted(proposed())), context={"suggest_corrections": False})
    Report.model_validate(report(contradicted()), context={"suggest_corrections": False})


def test_a_proposed_correction_must_be_complete_and_cite_evidence():
    for missing in ("span", "original_text", "replacement_text", "evidence"):
        data = proposed()
        data.pop(missing)
        with pytest.raises(ValidationError, match="proposed correction needs"):
            Correction.model_validate(data)
    with pytest.raises(ValidationError, match="original_text length"):
        Correction.model_validate(proposed() | {"original_text": "€9"})


@pytest.mark.parametrize("status", ["SUPPORTED", "NOT_ENOUGH_EVIDENCE"])
def test_corrections_only_on_contradicted(status):
    extra = {"evidence": [], "confidence": 0.0, "needs_human_review": True} if status == "NOT_ENOUGH_EVIDENCE" else {}
    with pytest.raises(ValidationError, match="only a CONTRADICTED verdict"):
        VerdictResult.model_validate(verdict(status=status, correction=proposed(), **extra))
    with pytest.raises(ValidationError, match="only a CONTRADICTED verdict"):
        VerdictResult.model_validate(verdict(status="ERROR", evidence=[], needs_human_review=True,
                                             error_code="INTERNAL_ERROR", correction={"status": "failed"}))


def test_duplicate_claim_ids_are_refused():
    data = report(verdict(), verdict())
    data["claims"][1]["claim"]["claim_id"] = "clm_0001"
    with pytest.raises(ValidationError, match="duplicate claim_id"):
        Report.model_validate(data)


# --- Mapping from the internal report -------------------------------------------------------------


def internal(name: str) -> VerificationReport:
    return VerificationReport.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))


def test_partial_failure_keeps_every_other_claims_result():
    source = internal("end_to_end/report.scripted.json")  # PARTIAL: one claim timed out
    public = to_public_report(source)
    assert [c.verdict.status.value for c in public.claims] == ["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE", "ERROR"]
    failed = public.claims[3].verdict
    assert failed.error_code.value == "PROVIDER_TIMEOUT" and failed.confidence == 0.0 and failed.needs_human_review
    assert public.metadata.content_hash == source.content_sha256 and public.request_id == source.request_id


def test_mapping_carries_evidence_confidence_and_the_correction():
    source = internal("verification_report.json")
    public = to_public_report(source)
    for entry, result in zip(public.claims, source.results):
        assert entry.claim.text == result.claim.text and entry.claim.span.start == result.claim.source_span.start
        assert entry.verdict.confidence == CONFIDENCE[result.evidence_strength]
        assert [e.quote for e in entry.verdict.evidence] == [c.quote for c in result.citations]
        assert entry.verdict.needs_human_review == result.requires_human_review
    correction = public.claims[1].verdict.correction
    assert correction.status.value == "proposed" and correction.replacement_text == source.results[1].correction.replacement_text


def test_mapping_without_suggest_corrections_returns_none():
    public = to_public_report(internal("verification_report.json"), suggest_corrections=False)
    assert all(c.verdict.correction is None for c in public.claims)


def test_requested_corrections_that_never_ran_are_not_hidden():
    source = internal("verification_report.json")
    data = json.loads(source.model_dump_json())
    data["results"][1].pop("correction")
    data["results"][1].pop("correction_attempt")
    data.pop("score")
    with pytest.raises(NotRepresentable, match="no correction was attempted"):
        to_public_report(VerificationReport.model_validate(data))


def test_a_failed_report_is_refused_not_emptied():
    """No results: the endpoint answers 503 instead (Phase 2 decision), never an empty claim list."""
    with pytest.raises(NotRepresentable, match="FAILED"):
        to_public_report(internal("verification_report_failed.json"))


def test_request_level_errors_with_results_go_to_metadata_errors():
    """Phase 2 decision: a report with results keeps them; its request-level errors are listed."""
    data = json.loads(internal("end_to_end/report.scripted.json").model_dump_json())
    data["errors"] = [{"code": "MALFORMED_MODEL_OUTPUT", "stage": "extraction", "message": "1 sentence was not classified.",
                       "retryable": True}]
    data.pop("score")
    public = to_public_report(VerificationReport.model_validate(data))
    assert len(public.claims) == 4
    assert [(e.code.value, e.message) for e in public.metadata.errors] == [("MALFORMED_MODEL_OUTPUT", "1 sentence was not classified.")]


def test_metadata_errors_use_the_engines_codes_and_bounded_messages():
    with pytest.raises(ValidationError):
        Report.model_validate(report(verdict()) | {"metadata": {"content_hash": HASH, "errors": [{"code": "MADE_UP", "message": "x"}]}})
    with pytest.raises(ValidationError):
        Report.model_validate(report(verdict()) | {"metadata": {"content_hash": HASH, "errors": [{"code": "INTERNAL_ERROR", "message": "x" * 501}]}})


def test_passage_mapping_keeps_location_text_and_score():
    passage = internal("verification_report.json").results[0].evidence[0]
    public = to_public_passage(passage)
    assert (public.location.start, public.location.end) == (passage.span.start, passage.span.end)
    assert public.text == passage.text and public.score == passage.retrieval.score


@pytest.mark.parametrize("confidence", [0.0, 0.33, 0.5])
def test_low_confidence_needs_human_review(confidence):
    with pytest.raises(ValidationError, match="low confidence needs human review"):
        VerdictResult.model_validate(verdict(confidence=confidence, needs_human_review=False))
    assert VerdictResult.model_validate(verdict(confidence=confidence, needs_human_review=True)).needs_human_review


@pytest.mark.parametrize("confidence", [0.67, 1.0])
def test_moderate_or_strong_support_may_skip_review(confidence):
    assert not VerdictResult.model_validate(verdict(confidence=confidence)).needs_human_review


def test_public_example_is_current_and_matches_the_json_schema():
    """examples/public/report.json is the public form of examples/end_to_end/report.scripted.json
    (a PARTIAL report: one claim failed, three kept). INKLOOM_REGENERATE_EXAMPLES=1 rewrites it."""
    text = to_public_report(internal("end_to_end/report.scripted.json")).model_dump_json(indent=2) + "\n"
    path = EXAMPLES / "public" / "report.json"
    if os.environ.get("INKLOOM_REGENERATE_EXAMPLES") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.read_text(encoding="utf-8") == text, "public/report.json is stale; regenerate it"
    schema = json.loads((EXAMPLES.parent / "schemas" / "public_report.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(json.loads(text))
