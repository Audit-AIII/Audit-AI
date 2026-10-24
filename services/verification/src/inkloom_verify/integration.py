"""Reference mapping from engine results to Member 3's Finding contract (contract/README.md).

The backend owns this mapping; this module gives it one tested implementation of the
engine-derived fields, so field names and status strings are not re-typed by hand. Fields the
backend owns (finding_id, severity, category, check_type, evidence ids) are not set.

Two suggestions are kept strictly apart:

* ``suggested_correction`` comes **only** from ``ClaimResult.correction``: an evidence-backed fix
  of a CONTRADICTED claim. It is None for every other claim.
* ``safer_wording`` comes **only** from ``ClaimResult.safer_wording``: a softened wording for an
  unverified claim, explicitly not evidence-backed (``safer_wording_evidence_backed`` is always
  False). It never fills ``suggested_correction``.
"""

from __future__ import annotations

from typing import Any

from inkloom_verify.schemas import ClaimResult, Correction, RuleFinding, SaferWording, Verdict

# contract/README.md, open decision 2: ERROR maps to "unverified", never "contradicted".
VERIFICATION_STATUS = {
    Verdict.SUPPORTED: "supported",
    Verdict.CONTRADICTED: "contradicted",
    Verdict.NOT_ENOUGH_EVIDENCE: "unverified",
    Verdict.ERROR: "unverified",
}
# A NOT_ENOUGH_EVIDENCE result whose approved references disagree (ClaimResult.conflicting_sources).
CONFLICTING_SOURCES_STATUS = "conflicting_sources"
EVIDENCE_RELATION = {Verdict.SUPPORTED: "supports", Verdict.CONTRADICTED: "contradicts"}


def _apply(result: ClaimResult, content_text: str, edit: Correction | SaferWording | None) -> str | None:
    if edit is None:
        return None
    span, target = result.claim.source_span, edit.target_span
    original = span.slice(content_text)
    return original[: target.start - span.start] + edit.replacement_text + original[target.end - span.start :]


def corrected_text(result: ClaimResult, content_text: str) -> str | None:
    """The claim's source text with the proposed correction applied, or None if none was proposed."""
    return _apply(result, content_text, result.correction)


def safer_text(result: ClaimResult, content_text: str) -> str | None:
    """The claim's source text with the safer wording applied, or None. Not evidence-backed."""
    return _apply(result, content_text, result.safer_wording)


def verification_status(result: ClaimResult) -> str:
    if result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and result.conflicting_sources:
        return CONFLICTING_SOURCES_STATUS
    return VERIFICATION_STATUS[result.verdict]


def finding_fields(result: ClaimResult, content_text: str) -> dict[str, Any]:
    """The Finding fields the engine can supply for one result.

    ``requires_human_review`` is true for everything except a SUPPORTED verdict on strong
    evidence: missing evidence, contradictions, conflicts and failures always go to a person.
    Evidence is the guard-validated citations only; ``doc_id`` is the engine's document id (the
    backend's source_version_id if it passes that as doc_id, as INTEGRATION.md recommends), and
    ``source_ids`` lists those ids once each, in citation order.
    """
    span = result.claim.source_span
    return {
        "engine_claim_id": result.claim.claim_id,
        "original_text": span.slice(content_text),
        "span": {"start": span.start, "end": span.end},
        "verification_status": verification_status(result),
        "explanation": result.model_rationale,
        "suggested_correction": corrected_text(result, content_text),
        "requires_human_review": result.requires_human_review,
        "evidence": _evidence(result),
    }


def _evidence(result: ClaimResult) -> list[dict[str, Any]]:
    relation = EVIDENCE_RELATION.get(result.verdict)
    return [{"doc_id": c.doc_id, "quote": c.quote, "relation": relation} for c in result.citations if relation]


# Finding fields the engine supplies that the shared contract (contract/schemas/finding.schema.json)
# does not have yet. Kept out of finding_fields so its output still validates against today's
# contract; Members 1 and 3 add them to the contract (and the UI) before the backend stores them.
PROPOSED_FINDING_FIELDS = ("source_ids", "safer_wording", "safer_wording_evidence_backed")


def proposed_finding_fields(result: ClaimResult, content_text: str) -> dict[str, Any]:
    """The proposed contract additions for one result (PROPOSED_FINDING_FIELDS)."""
    return {
        "source_ids": list(dict.fromkeys(item["doc_id"] for item in _evidence(result))),
        "safer_wording": safer_text(result, content_text),
        "safer_wording_evidence_backed": False,
    }


# --- Rule findings (rules.evaluate_rules) ---------------------------------------------------------

# Engine fields of a rule finding that the shared contract does not have yet; Members 1 and 3 add
# them to contract/schemas/finding.schema.json before the backend stores them (RULES_HANDOFF.md).
PROPOSED_RULE_FINDING_FIELDS = ("rule_id", "rule_type", "scope", "suggestion_basis", "source_ids")


def rule_finding_fields(finding: RuleFinding) -> dict[str, Any]:
    """The Finding fields for one rule finding; validates against today's shared contract once the
    backend adds finding_id and evidence ids (and maps evidence doc_id to its source ids)."""
    return {
        "category": finding.category.value,
        "severity": finding.severity.value,
        "original_text": finding.original_text,
        "span": {"start": finding.span.start, "end": finding.span.end},
        "check_type": "rule",
        "explanation": finding.explanation,
        "verification_status": "not_applicable",
        "suggested_correction": finding.suggested_correction,
        "requires_human_review": True,
        "evidence": [{"doc_id": e.source_id, "quote": e.quote, "relation": e.relation} for e in finding.evidence],
    }


def proposed_rule_finding_fields(finding: RuleFinding) -> dict[str, Any]:
    """PROPOSED_RULE_FINDING_FIELDS for one rule finding."""
    return {
        "rule_id": finding.rule_id,
        "rule_type": finding.rule_type.value,
        "scope": finding.scope,
        "suggestion_basis": finding.suggestion_basis,
        "source_ids": list(finding.source_ids),
    }
