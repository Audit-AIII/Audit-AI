"""Phase 5: a correction may only use facts the cited evidence gives: values with their units, whole
dates and names. It is traceable to its evidence, and it is never offered for anything but a
CONTRADICTED claim, including when the references conflict."""

from pathlib import Path

import pytest

from e2e_support import data_block
from inkloom_verify.correction import ClaimCorrector, CorrectionConfig, correction_issues
from inkloom_verify.evaluation.corrections import contradicted_result, load_cases
from inkloom_verify.evaluation.runner import load_records
from inkloom_verify.integration import corrected_text
from inkloom_verify.pipeline import verify_request
from inkloom_verify.providers.fake import ResponderProvider, ScriptedProvider
from inkloom_verify.schemas import (
    ClaimResult,
    CorrectionIssueCode,
    CorrectionStatus,
    EvidenceStrength,
    GuardRejectionReason,
    Verdict,
    VerificationRequest,
)
from inkloom_verify.verification import ClaimVerifier

ROOT = Path(__file__).resolve().parents[1]
CASES = {c.case_id: c for c in load_cases(ROOT / "eval" / "data" / "corrections_v1.jsonl")}
I = CorrectionIssueCode
PRICE = ["Price: €129 (EU launch price). Battery: up to 36 hours with the case."]


# --- The deterministic check, in the claim's own sentence ----------------------------------------


@pytest.mark.parametrize(
    ("original", "replacement", "quotes", "before", "after", "codes"),
    [
        # supported values, dates and names pass
        ("€99", "€129", PRICE, "Lumen Pods cost ", ".", []),
        ("99", "129", PRICE, "Lumen Pods cost €", ".", []),  # the currency sits outside the target
        ("2 May 2026", "2 April 2026", ["Launch date: 2 April 2026"], "Lumen Pods launch on ", ".", []),
        ("Porto", "Lisbon", ["Lumen Goods was founded in 2019 in Lisbon, Portugal"], "Lumen Goods was founded in ", ".", []),
        # changed numbers: a value the evidence gives for something else
        ("€99", "€36", PRICE, "Lumen Pods cost ", ".", [I.UNSUPPORTED_ADDITION]),
        ("36 hours", "129 hours", PRICE, "It lasts ", " with the case.", [I.UNSUPPORTED_ADDITION]),
        ("7 g", "6 g", ["Weight: 5.2 g per earbud"], "They weigh ", " per earbud.", [I.UNSUPPORTED_ADDITION]),
        # units must survive
        ("€99", "129", PRICE, "Lumen Pods cost ", ".", [I.DROPS_UNIT]),
        ("7 g", "5.2", ["Weight: 5.2 g per earbud"], "They weigh ", " per earbud.", [I.DROPS_UNIT]),
        # changed dates: the day, the month, or a year borrowed from elsewhere
        ("2 May 2026", "12 April 2026", ["Launch date: 2 April 2026"], "Launch on ", ".", [I.UNSUPPORTED_ADDITION]),
        ("2 May 2026", "2 April 2025", ["Launch date: 2 April 2026. Founded 2025."], "Launch on ", ".", [I.UNSUPPORTED_ADDITION]),
        # invented names
        ("Porto", "Lisbon by Ana Ribeiro", ["Lumen Goods was founded in 2019 in Lisbon"], "Founded in ", ".", [I.UNSUPPORTED_ADDITION]),
        ("Tomás Silva", "Marta Costa", ["Ana Ribeiro is the chief executive officer."], "", " is the CEO.", [I.UNSUPPORTED_ADDITION]),
        # unsupported facts added beside a supported fix
        ("€99", "€129 including VAT", PRICE, "Lumen Pods cost ", ".", [I.UNSUPPORTED_ADDITION]),
    ],
    ids=lambda v: v if isinstance(v, str) and len(v) < 25 else None,
)
def test_every_value_date_name_and_unit_must_come_from_the_evidence(original, replacement, quotes, before, after, codes):
    assert [i.code for i in correction_issues(original, replacement, quotes, before, after)] == codes


# --- Through the corrector, with a scripted model -------------------------------------------------


def corrector_run(case_id: str, original: str, replacement: str):
    case = CASES[case_id]
    result, content = contradicted_result(case)
    quote = result.citations[0].quote
    supported = {"verdict": "SUPPORTED", "citations": [{"passage": "P1", "quote": quote}], "rationale": "P1."}
    provider = ScriptedProvider(
        {"status": "corrected", "original_text": original, "replacement_text": replacement, "citations": ["C1"], "reason": "C1."},
        supported,
    )
    corrected = ClaimCorrector(provider, ClaimVerifier(provider, case.references), CorrectionConfig()).correct(result, content)
    ClaimResult.model_validate(corrected.model_dump())  # always a valid contract object
    return corrected, content


@pytest.mark.parametrize(
    ("case_id", "original", "replacement", "code"),
    [
        ("corr-v1-027", "€99", "129", I.DROPS_UNIT),  # currency dropped
        ("corr-v1-027", "€99", "€12", I.UNSUPPORTED_ADDITION),  # a number not in the evidence
        ("corr-v1-028", "2 May 2026", "2 April 2025", I.UNSUPPORTED_ADDITION),  # changed year
        ("corr-v1-024", "Tomás Silva", "Marta Costa", I.UNSUPPORTED_ADDITION),  # invented name
    ],
)
def test_unsafe_proposals_are_never_offered(case_id, original, replacement, code):
    corrected, _ = corrector_run(case_id, original, replacement)
    assert corrected.verdict is Verdict.CONTRADICTED  # the verdict is kept
    assert corrected.correction is None and corrected.correction_attempt.status is CorrectionStatus.NEEDS_HUMAN_REVIEW
    assert code in [i.code for i in corrected.correction_attempt.issues]
    assert corrected.requires_human_review


def test_a_proposed_correction_is_traceable_to_its_evidence():
    corrected, content = corrector_run("corr-v1-027", "€99", "€129")
    correction = corrected.correction
    assert corrected.correction_attempt.status is CorrectionStatus.PROPOSED
    assert corrected.correction_attempt.recheck_verdict is Verdict.SUPPORTED
    assert correction.original_text == content.text[correction.target_span.start:correction.target_span.end]  # in the draft
    assert corrected.claim.source_span.contains(correction.target_span)
    accepted = {(c.passage_id, c.quote) for c in corrected.citations}
    assert correction.citations and {(c.passage_id, c.quote) for c in correction.citations} <= accepted
    assert all(c.quote in {p.text for p in corrected.evidence if p.passage_id == c.passage_id}.pop() for c in correction.citations)
    assert corrected_text(corrected, content.text) == "Lumen Pods cost €129."


# --- Never for anything but CONTRADICTED, and never under conflicting evidence --------------------


def test_conflicting_evidence_gets_no_correction():
    """The model answers CONTRADICTED from the firmware note (14 hours); the fact sheet says 12.
    The guard downgrades it to NOT_ENOUGH_EVIDENCE, so the corrector is never asked."""
    record = {r.record_id: r for r in load_records(ROOT / "eval" / "dataset.jsonl")}["v2-c01"]
    request = VerificationRequest(request_id="req-c01", tenant_id="tenant-eval", content={"text": record.claim_text},
                                  references=record.references)
    asked = []

    def respond(call):
        asked.append(call.schema_name)
        if call.schema_name == "claim_extraction":
            return {"statements": [{"sentence_id": s["id"], "kind": "factual", "claims": [{"text": s["text"], "source_quote": s["text"]}]}
                                   for s in data_block(call, "content_json")["sentences"]]}
        if call.schema_name == "claim_verification":
            for p in data_block(call, "verification_input_json")["passages"]:
                if "14 hours" in p["text"]:
                    quote = next(s.strip() + "." for s in p["text"].split(".") if "14 hours" in s)
                    return {"verdict": "CONTRADICTED", "citations": [{"passage": p["label"], "quote": quote}], "rationale": "x"}
        raise AssertionError(f"unexpected call {call.schema_name}")

    report = verify_request(request, ResponderProvider(respond))
    [result] = report.results
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and result.correction is None and result.correction_attempt is None
    assert [r.reason for r in result.citation_guard.rejected] == [GuardRejectionReason.CONFLICTING_EVIDENCE]
    assert "claim_correction" not in asked
    assert result.evidence_strength is EvidenceStrength.NONE and result.requires_human_review  # confidence: none
