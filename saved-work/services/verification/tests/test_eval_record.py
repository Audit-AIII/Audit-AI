import json

import pytest
from pydantic import ValidationError

from inkloom_verify.schemas import EvalRecord, Verdict

from conftest import EXAMPLES


@pytest.fixture
def records() -> list[dict]:
    lines = (EXAMPLES / "eval_records.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def check(data: dict, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        EvalRecord.model_validate(data)


def test_example_records_are_valid(records):
    verdicts = [EvalRecord.model_validate(r).expected_verdict for r in records]
    assert verdicts == [Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE]


def test_error_is_not_a_label(records):
    records[1]["expected_verdict"] = "ERROR"
    check(records[1], "not a label")


@pytest.mark.parametrize("verdict", ["SUPPORTED", "CONTRADICTED"])
def test_definite_label_requires_gold_evidence(records, verdict):
    records[1]["expected_verdict"] = verdict
    check(records[1], "requires gold_evidence")


def test_not_enough_evidence_label_rejects_gold_evidence(records):
    records[0]["expected_verdict"] = "NOT_ENOUGH_EVIDENCE"
    check(records[0], "must not have gold_evidence")


def test_gold_evidence_must_name_a_reference(records):
    records[0]["gold_evidence"][0]["doc_id"] = "missing-doc"
    check(records[0], "unknown doc_id missing-doc")


def test_gold_evidence_must_fit_the_document(records):
    length = len(records[0]["references"][0]["text"])
    records[0]["gold_evidence"][0]["span"] = {"start": length - 1, "end": length + 1}
    check(records[0], "exceeds document")


def test_duplicate_references_rejected(records):
    records[0]["references"].append(records[0]["references"][0])
    check(records[0], "duplicate reference doc_id")
