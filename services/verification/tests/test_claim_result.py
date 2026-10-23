import pytest
from pydantic import ValidationError

from inkloom_verify.schemas import ClaimResult, Verdict


def check(data: dict, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        ClaimResult.model_validate(data)


def test_examples_are_valid(supported_result, contradicted_result, error_result):
    assert ClaimResult.model_validate(supported_result).verdict is Verdict.SUPPORTED
    assert ClaimResult.model_validate(contradicted_result).correction is not None
    assert ClaimResult.model_validate(error_result).error is not None


@pytest.mark.parametrize("verdict", ["SUPPORTED", "CONTRADICTED"])
def test_definite_verdict_requires_a_citation(supported_result, verdict):
    supported_result.update(verdict=verdict, citations=[])
    check(supported_result, "requires at least one citation")


def test_rationale_is_not_evidence(supported_result):
    supported_result.update(citations=[], model_rationale="The spec clearly says 24 hours.")
    check(supported_result, "requires at least one citation")


def test_not_enough_evidence_with_considered_passages_is_valid(supported_result):
    supported_result.update(verdict="NOT_ENOUGH_EVIDENCE", citations=[])
    supported_result.pop("requires_human_review")  # re-derived from the new verdict
    supported_result.pop("evidence_strength")
    result = ClaimResult.model_validate(supported_result)
    assert result.evidence and not result.citations


@pytest.mark.parametrize("verdict", ["NOT_ENOUGH_EVIDENCE", "ERROR"])
def test_non_definite_verdict_rejects_citations(supported_result, error_result, verdict):
    supported_result.update(verdict=verdict, error=dict(error_result["error"]))
    check(supported_result, "must not carry citations")


def test_error_verdict_requires_error(error_result):
    del error_result["error"]
    check(error_result, "ERROR requires an error")


@pytest.mark.parametrize("verdict", ["SUPPORTED", "NOT_ENOUGH_EVIDENCE"])
def test_error_only_on_error_verdict(supported_result, error_result, verdict):
    supported_result.update(verdict=verdict, error=error_result["error"])
    if verdict == "NOT_ENOUGH_EVIDENCE":
        supported_result["citations"] = []
    check(supported_result, "must not carry an error")


def test_error_claim_id_must_match(error_result):
    error_result["error"]["claim_id"] = "clm_9999"
    check(error_result, "does not match the claim")


def test_unknown_verdict_rejected(supported_result):
    supported_result["verdict"] = "PARTIALLY_SUPPORTED"
    check(supported_result, "verdict")


@pytest.mark.parametrize("verdict", ["SUPPORTED", "NOT_ENOUGH_EVIDENCE", "ERROR"])
def test_correction_only_on_contradicted(contradicted_result, error_result, verdict):
    contradicted_result["verdict"] = verdict
    if verdict != "SUPPORTED":
        contradicted_result["citations"] = []
    if verdict == "ERROR":
        contradicted_result["error"] = dict(error_result["error"], claim_id="clm_0002")
    check(contradicted_result, "correction is only allowed on a CONTRADICTED claim")


def test_citation_must_reference_listed_evidence(supported_result):
    supported_result["evidence"] = []
    check(supported_result, "not in evidence")


def test_citation_must_name_the_passage_document(supported_result):
    supported_result["citations"][0]["doc_id"] = "another-doc"
    check(supported_result, "different document")


def test_citation_must_name_the_passage_document_version(supported_result):
    supported_result["citations"][0]["doc_text_sha256"] = "0" * 64
    check(supported_result, "different document")


def test_citation_span_must_lie_inside_passage(supported_result):
    citation = supported_result["citations"][0]
    start = supported_result["evidence"][0]["span"]["start"] - 1
    citation["quote_span"] = {"start": start, "end": start + len(citation["quote"])}
    check(supported_result, "outside passage")


def test_paraphrased_quote_rejected(supported_result):
    citation = supported_result["citations"][0]
    citation["quote"] = "keeps beverages cold for up to 24 hours"[: len(citation["quote"])]
    check(supported_result, "not the verbatim text")


def test_duplicate_citation_rejected(supported_result):
    supported_result["citations"].append(supported_result["citations"][0])
    check(supported_result, "duplicate citation")


def test_duplicate_evidence_rejected(supported_result):
    supported_result["evidence"].append(supported_result["evidence"][0])
    check(supported_result, "duplicate passage_id")


def test_correction_must_stay_inside_claim_span(contradicted_result):
    claim = contradicted_result["claim"]
    start = claim["source_span"]["start"]
    claim["source_span"] = {"start": start, "end": start + 5}
    claim["normalized_text"], claim["text"] = claim["text"], claim["text"][:5]  # still the exact content slice
    check(contradicted_result, "outside the claim's source_span")


def test_correction_must_cite_a_result_citation(contradicted_result, supported_result):
    contradicted_result["evidence"].append(supported_result["evidence"][0])
    contradicted_result["citations"] = [supported_result["citations"][0]]
    check(contradicted_result, "not a citation of this result")


def test_rationale_length_limit(supported_result):
    supported_result["model_rationale"] = "x" * 2001
    check(supported_result, "model_rationale")
