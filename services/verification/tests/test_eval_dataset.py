"""Integrity checks on the shipped evaluation dataset. They check structure, not truth: whether a
label is right is a human judgement recorded in label_rationale and reviewed_by."""

from collections import Counter
from pathlib import Path

import pytest

from inkloom_verify.evaluation.runner import load_records
from inkloom_verify.schemas import EvalCategory, EvalSplit, Verdict

DATASET = Path(__file__).resolve().parents[1] / "eval" / "data" / "verification_v1.jsonl"
INJECTION_DOCS = {"supplier-note", "agency-brief"}


@pytest.fixture(scope="module")
def records():
    return load_records(DATASET)


def test_size_and_balance(records):
    assert len(records) == 50
    verdicts = Counter(r.expected_verdict for r in records)
    assert set(verdicts) == {Verdict.SUPPORTED, Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE}
    assert min(verdicts.values()) >= 10


def test_heldout_split_covers_every_verdict(records):
    heldout = [r for r in records if r.split is EvalSplit.HELDOUT]
    assert len(heldout) == 15
    assert Counter(r.expected_verdict for r in heldout) == {
        Verdict.SUPPORTED: 5,
        Verdict.CONTRADICTED: 5,
        Verdict.NOT_ENOUGH_EVIDENCE: 5,
    }


@pytest.mark.parametrize(
    "category",
    [
        EvalCategory.NUMERIC,
        EvalCategory.DATE,
        EvalCategory.NAMED_ENTITY,
        EvalCategory.COMPOUND,
        EvalCategory.AMBIGUOUS,
        EvalCategory.ABSENT_FACT,
        EvalCategory.IRRELEVANT_REFERENCES,
        EvalCategory.PROMPT_INJECTION,
    ],
)
def test_required_categories_are_represented(records, category):
    assert any(category in r.categories for r in records)


def test_compound_claims_cover_every_verdict(records):
    assert {r.expected_verdict for r in records if EvalCategory.COMPOUND in r.categories} == set(
        [Verdict.SUPPORTED, Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE]
    )


def test_every_label_has_a_rationale_and_definite_labels_have_evidence(records):
    for record in records:
        assert len(record.label_rationale) >= 20, record.record_id
        if record.expected_verdict in (Verdict.SUPPORTED, Verdict.CONTRADICTED):
            assert record.gold_evidence, record.record_id


def test_injection_records_include_an_injection_document_never_used_as_evidence(records):
    injection = [r for r in records if EvalCategory.PROMPT_INJECTION in r.categories]
    assert len(injection) >= 3
    for record in injection:
        assert INJECTION_DOCS & {d.doc_id for d in record.references}, record.record_id
        assert not INJECTION_DOCS & {g.doc_id for g in record.gold_evidence}, record.record_id


def test_injection_documents_only_appear_in_injection_records(records):
    for record in records:
        if INJECTION_DOCS & {d.doc_id for d in record.references}:
            assert EvalCategory.PROMPT_INJECTION in record.categories, record.record_id


def test_irrelevant_reference_records_have_no_evidence(records):
    for record in records:
        if EvalCategory.IRRELEVANT_REFERENCES in record.categories:
            assert record.expected_verdict is Verdict.NOT_ENOUGH_EVIDENCE
            assert record.gold_evidence == []


def test_shared_documents_are_identical_across_records(records):
    """Each doc_id must mean one exact text everywhere, or results are not comparable."""
    hashes: dict[str, set[str]] = {}
    for record in records:
        for document in record.references:
            hashes.setdefault(document.doc_id, set()).add(document.text_sha256)
    assert all(len(h) == 1 for h in hashes.values()), hashes
