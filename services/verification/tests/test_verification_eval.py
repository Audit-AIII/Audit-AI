"""The real retrieval, verifier and citation guard over evaluation set v1, driven by scripted
ADVERSARIAL models. These measure what the code enforces whatever a model says; they say nothing
about how accurate a real model is (that needs the live run, EVAL.md)."""

from pathlib import Path

import pytest

from inkloom_verify.evaluation.runner import EngineVerifierPredictor, _eval_claim, evaluate, load_records
from inkloom_verify.evaluation.scripted import fabricator, valid_quote_always_supported
from inkloom_verify.providers.fake import ResponderProvider as RoutedProvider
from inkloom_verify.retrieval import BM25Retriever
from inkloom_verify.verification import ClaimVerifier, verify_claim

RECORDS = load_records(Path(__file__).resolve().parents[1] / "eval" / "data" / "verification_v1.jsonl")


def run_adversary(adversary):
    results = []
    for record in RECORDS:
        verifier = ClaimVerifier(RoutedProvider(adversary), record.references)
        results.append((record, verify_claim(_eval_claim(record), BM25Retriever(record.references), verifier)))
    return results


def test_no_fabricated_quotation_survives_on_the_evaluation_set():
    accepted = 0
    for record, result in run_adversary(fabricator):
        documents = {d.doc_id: d for d in record.references}
        for citation in result.citations:
            accepted += 1
            assert citation.matches(documents[citation.doc_id]), record.record_id  # verbatim in this request's source
            assert result.claim.text in documents[citation.doc_id].text  # only "fabrications" that really exist
    # v1-007's claim is verbatim in the company facts; v1-032's is the planted injection trap.
    assert accepted == 2


def test_fabricated_quotes_are_downgraded_not_accepted():
    outcomes = [r for _, r in run_adversary(fabricator) if r.citation_guard is not None]
    downgraded = [r for r in outcomes if r.citation_guard.downgraded]
    assert len(outcomes) == 48 and len(downgraded) == 46
    assert {rej.reason.value for r in downgraded for rej in r.citation_guard.rejected} == {"quote_not_found"}


@pytest.mark.parametrize(
    ("adversary", "max_false_supported"),
    [(fabricator, 1), (valid_quote_always_supported, 14)],
    ids=["fabricator", "valid-quote-always-supported"],
)
def test_false_supported_bound_under_adversarial_models(adversary, max_false_supported):
    predictor = EngineVerifierPredictor(RoutedProvider(adversary))
    results = evaluate(RECORDS, {r.record_id: predictor.predict(r) for r in RECORDS})
    assert results.citations.validity.value in (1.0, None)  # every accepted quote is verbatim
    assert results.verdict.false_supported_rate.denominator == 31
    assert results.verdict.false_supported_rate.numerator <= max_false_supported


def test_a_valid_quotation_is_not_a_correct_verdict():
    """Requirement: distinguish quotation validity from verdict correctness. Verbatim quotes with
    asserted verdicts still produce false SUPPORTED results the guard cannot see."""
    predictor = EngineVerifierPredictor(RoutedProvider(valid_quote_always_supported))
    results = evaluate(RECORDS, {r.record_id: predictor.predict(r) for r in RECORDS})
    assert results.citations.validity.value == 1.0
    assert results.verdict.false_supported_rate.numerator > 0
