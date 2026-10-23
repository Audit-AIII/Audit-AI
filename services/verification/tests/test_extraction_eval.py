"""The extraction evaluation (Phase 6): a labelled set of 24 paragraphs, an oracle replay that checks
the code, adversaries that check what the code enforces, and metrics that can see what it cannot."""

from pathlib import Path

import pytest

from inkloom_verify import extraction as extraction_module
from inkloom_verify.chunking import sentence_spans
from inkloom_verify.evaluation.extraction import (
    ADVERSARIES,
    ExtractionRecord,
    _embellish,
    evaluate_extraction,
    extract_all,
    load_extraction_records,
    oracle,
    score,
)
from inkloom_verify.extraction import rewrite_problems
from inkloom_verify.providers.fake import ResponderProvider
from inkloom_verify.schemas import MAX_CLAIM_CHARS

DATASET = Path(__file__).resolve().parents[1] / "eval" / "data" / "extraction_v1.jsonl"
RECORDS = load_extraction_records(DATASET)


# --- The dataset --------------------------------------------------------------------------------


def test_at_least_twenty_paragraphs_covering_the_required_cases():
    assert len(RECORDS) >= 20 and sum(len(r.claims) for r in RECORDS) == 33
    categories = {c for r in RECORDS for c in r.categories}
    assert {"compound", "opinion", "numbers", "dates", "negation", "qualifier", "pronoun", "attribution",
            "marketing_only", "list", "unicode", "non_bmp", "abbreviation", "number_words", "may_verb"} <= categories
    assert any(not r.claims for r in RECORDS)  # paragraphs with nothing to check
    assert {r.split for r in RECORDS} == {"dev", "heldout"}


def test_every_label_is_the_exact_text_at_its_offsets():
    for record in RECORDS:
        for claim in record.claims:
            assert record.text[claim.start:claim.end] == claim.text


def test_a_wrong_offset_is_refused():
    data = RECORDS[0].model_dump()
    data["claims"][0]["end"] -= 1
    with pytest.raises(ValueError, match="is not the text at"):
        ExtractionRecord.model_validate(data)


def test_every_labelled_claim_lies_inside_one_extractor_sentence():
    for record in RECORDS:
        spans = sentence_spans(record.text, MAX_CLAIM_CHARS)
        for claim in record.claims:
            assert any(s.start <= claim.start and claim.end <= s.end for s in spans), (record.record_id, claim.text)


def test_labelled_statements_follow_the_rewording_rules():
    """The labelling rule: a standalone wording adds nothing that is not in the paragraph."""
    for record in RECORDS:
        for claim in record.claims:
            if claim.statement:
                assert rewrite_problems(claim.statement, claim.text, record.text) == [], (record.record_id, claim.statement)


def test_labels_are_not_yet_human_reviewed():
    assert all(not r.reviewed_by for r in RECORDS)  # stated in every report until someone reviews them


# --- The oracle checks the code -------------------------------------------------------------------


def test_the_oracle_replay_returns_every_labelled_claim_exactly():
    results = extract_all(RECORDS, lambda r: ResponderProvider(oracle(r)))
    metrics = score(RECORDS, results)
    assert metrics.exact_span_matches.value == 1.0 and metrics.claim_precision.value == 1.0
    assert metrics.atomicity_violations == metrics.opinion_leakage == metrics.slice_violations == 0
    for record, result in zip(RECORDS, results):
        assert not result.warnings and not result.errors, record.record_id
        for claim in result.claims:
            assert record.text[claim.source_span.start:claim.source_span.end] == claim.text
            label = next(c for c in record.claims if (c.start, c.end) == (claim.source_span.start, claim.source_span.end))
            assert claim.statement == (label.statement or label.text)


def test_compound_sentences_become_separate_atomic_claims():
    record = next(r for r in RECORDS if r.record_id == "x-013")  # rated IPX4, weigh 5.2 g and come in three colours
    [result] = extract_all([record], lambda r: ResponderProvider(oracle(r)))
    assert [c.text for c in result.claims] == ["Lumen Pods are rated IPX4", "weigh 5.2 g", "come in three colours"]
    assert [c.statement for c in result.claims][1:] == ["Lumen Pods weigh 5.2 g.", "Lumen Pods come in three colours."]


# --- Adversaries: what the code enforces, and what the metrics see -------------------------------


def test_no_embellished_wording_survives():
    metrics = score(RECORDS, extract_all(RECORDS, lambda r: ResponderProvider(ADVERSARIES["embellisher"](r))), _embellish)
    assert metrics.statements_changed_unsafely == 0
    assert metrics.slice_violations == 0 and metrics.claim_recall.value == 1.0  # safe fallback to the sentence


def test_the_unsafe_wording_metric_would_see_a_broken_guard(monkeypatch):
    """Not vacuous: switch the rewording rules off and the embellishments are counted."""
    monkeypatch.setattr(extraction_module, "rewrite_problems", lambda *a: [])
    metrics = score(RECORDS, extract_all(RECORDS, lambda r: ResponderProvider(ADVERSARIES["embellisher"](r))), _embellish)
    assert metrics.statements_changed_unsafely == 33


def test_merging_and_opinion_extraction_are_measured_not_hidden():
    merged = score(RECORDS, extract_all(RECORDS, lambda r: ResponderProvider(ADVERSARIES["merger"](r))))
    assert merged.atomicity_violations == 3  # x-002, x-013, x-023
    leaked = score(RECORDS, extract_all(RECORDS, lambda r: ResponderProvider(ADVERSARIES["opinion_leaker"](r))))
    assert leaked.opinion_leakage == 9 and leaked.claim_precision.value < 1.0


def test_the_report_section_has_no_live_numbers_without_a_provider():
    section = evaluate_extraction(RECORDS[:3])
    assert section["live"] is None and set(section["adversaries"]) == set(ADVERSARIES)
