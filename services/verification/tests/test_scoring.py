"""Evidence strength and human-review decisions (Phase 5, approved rules), and correction
traceability through the full pipeline."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from e2e_support import CONTENT, CONTRADICTED_CLAIM, DOCS, RoutedProvider, careful_model, request
from inkloom_verify.pipeline import verify_request
from inkloom_verify.schemas import (
    ClaimResult,
    EvidenceStrength,
    ReportScore,
    ReviewReason,
    Verdict,
    evidence_strength,
)
from inkloom_verify.scope import check_report_scope

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
S, M, W, NONE = EvidenceStrength.STRONG, EvidenceStrength.MODERATE, EvidenceStrength.WEAK, EvidenceStrength.NONE


def example(index: int) -> dict:
    report = json.loads((EXAMPLES / "verification_report.json").read_text(encoding="utf-8"))
    result = report["results"][index]
    result.pop("evidence_strength")
    result.pop("requires_human_review")
    result.pop("review_reasons", None)
    return result


def build(data: dict) -> ClaimResult:
    return ClaimResult.model_validate(data)


# --- The rules ---------------------------------------------------------------------------------


def test_supported_with_a_figure_from_the_top_passage_is_strong():
    result = build(example(0))  # "...cold for up to 24 hours", cited from the rank-1 passage
    assert result.evidence_strength is S and result.requires_human_review is False


def test_supported_without_figures_from_the_top_passage_is_moderate():
    data = example(0)
    data["claim"]["normalized_text"] = "The Lumen Bottle keeps drinks cold."  # the statement checked
    result = build(data)
    assert result.evidence_strength is M and result.requires_human_review is False


def test_support_from_a_lower_ranked_passage_only_is_weak_and_needs_review():
    data = example(0)
    data["evidence"][0]["retrieval"]["rank"] = 2
    result = build(data)
    assert result.evidence_strength is W and result.requires_human_review is True


def test_two_accepted_citations_are_strong_even_without_figures():
    data = example(0)
    data["claim"]["normalized_text"] = "The Lumen Bottle keeps drinks cold."  # the statement checked
    passage = data["evidence"][0]
    second = copy.deepcopy(data["citations"][0])
    words = passage["text"].split()
    second["quote"] = " ".join(words[-4:])
    start = passage["span"]["start"] + passage["text"].rindex(second["quote"])
    second["quote_span"] = {"start": start, "end": start + len(second["quote"])}
    data["citations"].append(second)
    assert build(data).evidence_strength is S


def test_contradicted_single_top_citation_is_moderate_and_always_reviewed():
    result = build(example(1))
    assert result.verdict is Verdict.CONTRADICTED
    assert result.evidence_strength is M and result.requires_human_review is True


@pytest.mark.parametrize("verdict", ["NOT_ENOUGH_EVIDENCE", "ERROR"])
def test_no_definite_verdict_means_no_strength_and_review(verdict):
    data = example(0)
    data.update(verdict=verdict, citations=[])
    if verdict == "ERROR":
        data["error"] = {"code": "PROVIDER_TIMEOUT", "stage": "verification", "message": "slow", "retryable": True}
    result = build(data)
    assert result.evidence_strength is NONE and result.requires_human_review is True


def test_a_rejected_citation_is_not_rescued_by_rank_or_score():
    """The guard downgraded the answer: top rank and a huge retrieval score change nothing."""
    data = example(0)
    data["evidence"][0]["retrieval"].update(rank=1, score=999.0)
    data.update(
        verdict="NOT_ENOUGH_EVIDENCE",
        citations=[],
        citation_guard={"model_verdict": "SUPPORTED", "downgraded": True, "rejected": [{"reason": "quote_not_found"}]},
        model_rationale="I am 99% confident.",
    )
    result = build(data)
    assert result.evidence_strength is NONE and result.requires_human_review is True


def test_retrieval_score_alone_never_changes_strength():
    low, high = example(0), example(0)
    low["evidence"][0]["retrieval"]["score"] = 0.01
    high["evidence"][0]["retrieval"]["score"] = 500.0
    assert build(low).evidence_strength is build(high).evidence_strength is S


# --- Neither field can be inflated -------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"evidence_strength": "strong"}, "evidence_strength must be weak"),
        ({"requires_human_review": False}, "must be true exactly when there is a review reason"),
    ],
)
def test_an_inflated_strength_or_review_flag_is_rejected(change, message):
    data = example(0)
    data["evidence"][0]["retrieval"]["rank"] = 2  # really weak
    data.update(change)
    with pytest.raises(ValidationError, match=message):
        build(data)


def test_strength_has_no_numeric_probability():
    assert all(not isinstance(value.value, (int, float)) for value in EvidenceStrength)
    assert "confidence" not in ClaimResult.model_fields


def test_strength_function_matches_the_contract():
    result = build(example(0))
    assert evidence_strength(result.verdict, result.claim.text, result.evidence, result.citations) is result.evidence_strength


# --- Report-level review -----------------------------------------------------------------------


def test_weak_support_is_a_report_review_reason():
    data = example(0)
    data["evidence"][0]["retrieval"]["rank"] = 2
    score = ReportScore.compute([build(data)], [])
    assert score.requires_human_review and score.review_reasons == [ReviewReason.WEAK_EVIDENCE]
    assert score.evidence_coverage.value == 1.0  # covered, but still reviewed


def test_strong_support_alone_needs_no_review():
    score = ReportScore.compute([build(example(0))], [])
    assert not score.requires_human_review and score.review_reasons == []


# --- Correction traceability through the full pipeline -----------------------------------------


def test_every_correction_traces_back_to_its_evidence_and_the_content():
    req = request()
    report = verify_request(req, RoutedProvider(careful_model))
    check_report_scope(req, report)
    [result] = [r for r in report.results if r.claim.text == CONTRADICTED_CLAIM]
    correction = result.correction
    assert correction is not None and result.correction_attempt.recheck_verdict is Verdict.SUPPORTED
    assert CONTENT[correction.target_span.start : correction.target_span.end] == correction.original_text
    assert result.claim.source_span.contains(correction.target_span)
    for citation in correction.citations:
        assert citation in result.citations  # backed by the evidence that established the contradiction
        assert citation.matches(DOCS[citation.doc_id])  # and that evidence is verbatim in its source
    assert result.claim.text == CONTRADICTED_CLAIM  # the original claim is kept unchanged
