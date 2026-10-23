"""Phase 4: references that disagree about a claim never yield an automatic verdict.

The engine does not know which document is authoritative, so a definite answer whose figure is
contradicted by another document is downgraded to NOT_ENOUGH_EVIDENCE with the reason
conflicting_evidence, and the report asks for review (CONTRACTS.md)."""

import json
import re
from pathlib import Path

import pytest

from e2e_support import data_block
from inkloom_verify.evaluation.runner import _eval_claim, load_records
from inkloom_verify.pipeline import verify_request
from inkloom_verify.providers.fake import ResponderProvider
from inkloom_verify.retrieval import BM25Retriever
from inkloom_verify.schemas import Claim, GuardRejectionReason, ReviewReason, Verdict, VerificationRequest
from inkloom_verify.verification import ClaimVerifier, verify_claim

ROOT = Path(__file__).resolve().parents[1]
RECORDS = {r.record_id: r for r in load_records(ROOT / "eval" / "dataset.jsonl")}
# The words in each claim that a one-sided model would quote as its evidence.
KEY = {"v2-c01": "12 hours", "v2-c02": "€129", "v2-c03": "2 April 2026", "v2-c04": "Ana Ribeiro", "v2-c05": "750 ml"}


def one_sided(verdict: str, key: str):
    """A model that answers ``verdict`` quoting the sentence of the first passage containing ``key``."""

    def respond(request):
        block = data_block(request, "verification_input_json")
        for passage in block["passages"]:
            for sentence in re.findall(r"[^.!?\n]+[.!?]?", passage["text"]):
                if key in sentence:
                    return {"verdict": verdict, "citations": [{"passage": passage["label"], "quote": sentence.strip()}],
                            "rationale": "One-sided reading."}
        return {"verdict": "NOT_ENOUGH_EVIDENCE", "citations": [], "rationale": "Not found."}

    return respond


def run(record_id: str, verdict: str = "SUPPORTED"):
    record = RECORDS[record_id]
    verifier = ClaimVerifier(ResponderProvider(one_sided(verdict, KEY[record_id])), record.references)
    return verify_claim(_eval_claim(record), BM25Retriever(record.references), verifier)


@pytest.mark.parametrize("record_id", ["v2-c01", "v2-c02", "v2-c03"])
def test_figure_conflicts_in_the_dataset_are_downgraded_and_sent_to_review(record_id):
    assert RECORDS[record_id].expected_verdict is Verdict.NOT_ENOUGH_EVIDENCE
    result = run(record_id)
    assert result.citation_guard.model_verdict is Verdict.SUPPORTED  # the model did answer SUPPORTED
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and result.citations == [] and result.requires_human_review
    assert [r.reason for r in result.citation_guard.rejected] == [GuardRejectionReason.CONFLICTING_EVIDENCE]


def test_a_conflict_about_something_else_leaves_a_supported_claim_alone():
    assert RECORDS["v2-c05"].expected_verdict is Verdict.SUPPORTED
    result = run("v2-c05")
    assert result.verdict is Verdict.SUPPORTED and result.citation_guard.rejected == []


def test_limitation_a_conflict_between_names_is_not_detected():
    """v2-c04: the company facts name Ana Ribeiro as CEO, the board minutes Marta Costa. No figure
    differs, so the guard cannot see the conflict; a one-sided SUPPORTED stands. Measured by the
    evaluation, documented in CONTRACTS.md."""
    assert RECORDS["v2-c04"].expected_verdict is Verdict.NOT_ENOUGH_EVIDENCE
    assert run("v2-c04").verdict is Verdict.SUPPORTED


def test_a_contradicted_answer_is_downgraded_when_another_document_backs_the_claim():
    """'Must not automatically produce CONTRADICTED': the model quotes the firmware note (14 hours)
    against the claim (12 hours), but the fact sheet says 12 hours."""
    record = RECORDS["v2-c01"]
    verifier = ClaimVerifier(ResponderProvider(one_sided("CONTRADICTED", "14 hours")), record.references)
    result = verify_claim(_eval_claim(record), BM25Retriever(record.references), verifier)
    assert result.citation_guard.model_verdict is Verdict.CONTRADICTED
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE
    assert [r.reason for r in result.citation_guard.rejected] == [GuardRejectionReason.CONFLICTING_EVIDENCE]


def test_a_plain_contradiction_still_stands():
    """One document, one different figure: that is a contradiction, not a conflict."""
    record = RECORDS["v2-c01"]
    single = [d for d in record.references if d.doc_id == "pods-fact-sheet"]
    verifier = ClaimVerifier(ResponderProvider(one_sided("CONTRADICTED", "12 hours")), single)
    text = "Lumen Pods offer up to 20 hours of playback per charge."
    claim = Claim(claim_id="clm_eval", text=text, source_span={"start": 0, "end": len(text)})
    result = verify_claim(claim, BM25Retriever(single), verifier)
    assert result.verdict is Verdict.CONTRADICTED


def test_the_report_names_conflicting_evidence_as_a_review_reason():
    record = RECORDS["v2-c01"]
    request = VerificationRequest(request_id="req-conflict", tenant_id="tenant-eval",
                                  content={"text": record.claim_text}, references=record.references)

    def respond(call):
        if call.schema_name == "claim_extraction":
            sentences = data_block(call, "content_json")["sentences"]
            return {"statements": [{"sentence_id": s["id"], "kind": "factual",
                                    "claims": [{"text": s["text"], "source_quote": s["text"]}]} for s in sentences]}
        return one_sided("SUPPORTED", "12 hours")(call)

    report = verify_request(request, ResponderProvider(respond))
    [result] = report.results
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE
    assert ReviewReason.CONFLICTING_EVIDENCE in report.score.review_reasons and report.score.requires_human_review
    json.loads(report.model_dump_json())  # serialises with the new enum values
