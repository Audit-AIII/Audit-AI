"""Two contract additions (audit decisions of 2026-10-24):

1. ``ClaimResult.conflicting_sources``: approved references disagree about the claim. The verdict
   stays NOT_ENOUGH_EVIDENCE; the flag is derived from the citation guard and maps to the shared
   contract's verification_status "conflicting_sources", always with human review.
2. ``ClaimResult.safer_wording`` vs ``ClaimResult.correction``: the safer wording (not
   evidence-backed, unverified claims only) and the correction (evidence-backed, contradicted
   claims only) never mix, in the contract, in the pipeline, or in the backend mapping helper.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from e2e_support import (
    CONTENT,
    CONTRADICTED_CLAIM,
    UNVERIFIED_CLAIM,
    RoutedProvider,
    careful_model,
    data_block,
    request,
)
from inkloom_verify.integration import (
    CONFLICTING_SOURCES_STATUS,
    PROPOSED_FINDING_FIELDS,
    finding_fields,
    proposed_finding_fields,
)
from inkloom_verify.pipeline import PipelineConfig, verify_request
from inkloom_verify.providers.fake import ScriptedProvider
from inkloom_verify.schemas import ClaimResult, ReferenceDocument, SaferWording, Verdict
from inkloom_verify.verification import ClaimVerifier
from test_verification import PODS, answer, verifier_input

NEWER = ReferenceDocument(
    doc_id="pods-fact-sheet-v3", text="Battery life: up to 10 hours of playback per charge."
)
CLAIM = "Lumen Pods offer up to 12 hours of playback per charge."


def conflicting_result() -> ClaimResult:
    provider = ScriptedProvider(
        answer("SUPPORTED", [("12 hours", "up to 12 hours of playback per charge")])
    )
    return ClaimVerifier(provider, [PODS, NEWER]).verify(verifier_input(CLAIM, PODS, NEWER))


# --- 1. conflicting_sources --------------------------------------------------------------------


def test_conflicting_approved_sources_set_the_flag_keep_the_verdict_and_go_to_a_person():
    result = conflicting_result()
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE  # the verdict is unchanged (decision 2b)
    assert result.conflicting_sources is True
    assert (
        result.requires_human_review is True
        and result.citations == []
        and result.correction is None
    )
    fields = finding_fields(result, CLAIM)
    assert fields["verification_status"] == CONFLICTING_SOURCES_STATUS == "conflicting_sources"
    assert fields["requires_human_review"] is True and fields["suggested_correction"] is None


def test_no_conflict_means_no_flag_and_the_usual_unverified_status():
    provider = ScriptedProvider(answer("NOT_ENOUGH_EVIDENCE", []))
    result = ClaimVerifier(provider, [PODS]).verify(
        verifier_input(CLAIM, PODS)
    )  # one document: nothing to conflict
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and result.conflicting_sources is False
    assert finding_fields(result, CLAIM)["verification_status"] == "unverified"


def test_the_flag_cannot_be_set_by_hand_against_the_guard():
    result = conflicting_result()
    data = result.model_dump()
    with pytest.raises(ValidationError, match="conflicting_sources must be true exactly"):
        ClaimResult.model_validate(data | {"conflicting_sources": False})
    plain = ScriptedProvider(answer("NOT_ENOUGH_EVIDENCE", []))
    unflagged = ClaimVerifier(plain, [PODS]).verify(verifier_input(CLAIM, PODS)).model_dump()
    with pytest.raises(ValidationError, match="conflicting_sources must be true exactly"):
        ClaimResult.model_validate(unflagged | {"conflicting_sources": True})


# --- 2. safer_wording never mixes with the correction ----------------------------------------


def _safer(result: ClaimResult, original: str, replacement: str) -> SaferWording:
    text = result.claim.text
    start = result.claim.source_span.start + text.index(original)
    return SaferWording(
        target_span={"start": start, "end": start + len(original)},
        original_text=original,
        replacement_text=replacement,
    )


def test_contract_refuses_safer_wording_on_any_verdict_but_not_enough_evidence(
    contradicted_result, supported_result
):
    for fixture in (contradicted_result, supported_result):
        result = ClaimResult.model_validate(fixture)
        span = result.claim.source_span
        wording = {
            "target_span": {"start": span.start, "end": span.end},
            "original_text": result.claim.text,
            "replacement_text": "softer",
        }
        with pytest.raises(ValidationError, match="only allowed on a NOT_ENOUGH_EVIDENCE claim"):
            ClaimResult.model_validate(fixture | {"safer_wording": wording})


def test_contract_refuses_a_correction_on_an_unverified_claim_so_both_can_never_coexist(
    contradicted_result,
):
    unverified = conflicting_result().model_dump()
    with pytest.raises(ValidationError, match="only allowed on a CONTRADICTED claim"):
        ClaimResult.model_validate(unverified | {"correction": contradicted_result["correction"]})


def test_safer_wording_is_labelled_and_can_never_claim_to_be_evidence_backed():
    result = conflicting_result()
    wording = _safer(result, "up to 12 hours", "long")
    assert wording.label == "safer_wording" and wording.evidence_backed is False
    with pytest.raises(ValidationError):
        SaferWording.model_validate(wording.model_dump() | {"evidence_backed": True})
    with pytest.raises(ValidationError):
        SaferWording.model_validate(wording.model_dump() | {"label": "correction"})


def test_mapping_puts_safer_wording_in_its_own_field_never_in_suggested_correction():
    result = conflicting_result()
    with_wording = ClaimResult.model_validate(
        result.model_dump()
        | {"safer_wording": _safer(result, "up to 12 hours", "long").model_dump()}
    )
    fields, proposed = (
        finding_fields(with_wording, CLAIM),
        proposed_finding_fields(with_wording, CLAIM),
    )
    assert fields["suggested_correction"] is None  # no evidence -> no suggested correction, ever
    assert "safer_wording" not in fields
    assert proposed["safer_wording"] == "Lumen Pods offer long of playback per charge."
    assert proposed["safer_wording_evidence_backed"] is False
    assert set(proposed) == set(PROPOSED_FINDING_FIELDS)


def _pipeline_with_softening():
    def model(req):
        if req.schema_name == "claim_softening":
            sentence = data_block(req, "softening_input_json")["sentence"]
            assert (
                sentence == UNVERIFIED_CLAIM
            )  # only the unverified claim is ever sent for softening
            return {
                "status": "softened",
                "original_text": "have active noise cancellation",
                "replacement_text": "are designed for noise cancellation",
                "citations": [],
                "reason": "No evidence.",
            }
        return careful_model(req)

    return verify_request(
        request(), RoutedProvider(model), PipelineConfig(suggest_safer_wording=True)
    )


def test_pipeline_never_puts_a_correction_and_a_safer_wording_on_the_same_claim():
    report = _pipeline_with_softening()
    by_text = {r.claim.text: r for r in report.results}
    contradicted, unverified = by_text[CONTRADICTED_CLAIM], by_text[UNVERIFIED_CLAIM]
    assert contradicted.correction is not None and contradicted.safer_wording is None
    assert unverified.safer_wording is not None and unverified.correction is None
    assert (
        unverified.verdict is Verdict.NOT_ENOUGH_EVIDENCE and unverified.requires_human_review
    )  # stays unverified
    assert all(not (r.correction and r.safer_wording) for r in report.results)
    assert report.provenance.prompt_versions["soften_claim"] == "soften-claim-v1"

    mapped = {
        r.claim.text: (finding_fields(r, CONTENT), proposed_finding_fields(r, CONTENT))
        for r in report.results
    }
    assert mapped[CONTRADICTED_CLAIM][0]["suggested_correction"] == "The Lumen Pods price is €129."
    assert mapped[CONTRADICTED_CLAIM][1]["safer_wording"] is None
    assert mapped[UNVERIFIED_CLAIM][0]["suggested_correction"] is None
    assert (
        mapped[UNVERIFIED_CLAIM][1]["safer_wording"]
        == "Lumen Pods are designed for noise cancellation."
    )


def test_safer_wording_is_off_by_default_so_no_softening_call_is_made():
    calls: list[str] = []

    def model(req):
        calls.append(req.schema_name)
        return careful_model(req)

    report = verify_request(request(), RoutedProvider(model))
    assert "claim_softening" not in calls and all(r.safer_wording is None for r in report.results)
    assert "soften_claim" not in report.provenance.prompt_versions


# --- source_ids (proposed contract field) -----------------------------------------------------


def test_source_ids_list_each_cited_document_once_and_are_empty_without_evidence():
    report = verify_request(request(), RoutedProvider(careful_model))
    for result in report.results:
        ids = proposed_finding_fields(result, CONTENT)["source_ids"]
        assert ids == list(dict.fromkeys(c.doc_id for c in result.citations))
        assert set(ids) <= {d.doc_id for d in request().references}  # only the authorised set
        if result.verdict in (Verdict.NOT_ENOUGH_EVIDENCE, Verdict.ERROR):
            assert ids == []
