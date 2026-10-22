"""Reference mapping from engine results to Member 3's Finding contract (contract/README.md).

The backend owns this mapping; this module gives it one tested implementation of the
engine-derived fields, so field names and status strings are not re-typed by hand. Fields the
backend owns (finding_id, severity, category, check_type, evidence ids, source ids) are not set.
"""

from __future__ import annotations

from typing import Any

from inkloom_verify.schemas import ClaimResult, Verdict

# contract/README.md, open decision 2: ERROR maps to "unverified", never "contradicted".
VERIFICATION_STATUS = {
    Verdict.SUPPORTED: "supported",
    Verdict.CONTRADICTED: "contradicted",
    Verdict.NOT_ENOUGH_EVIDENCE: "unverified",
    Verdict.ERROR: "unverified",
}
EVIDENCE_RELATION = {Verdict.SUPPORTED: "supports", Verdict.CONTRADICTED: "contradicts"}


def corrected_text(result: ClaimResult, content_text: str) -> str | None:
    """The claim's source text with the proposed correction applied, or None if none was proposed."""
    if result.correction is None:
        return None
    span, target = result.claim.source_span, result.correction.target_span
    original = span.slice(content_text)
    return original[: target.start - span.start] + result.correction.replacement_text + original[target.end - span.start :]


def finding_fields(result: ClaimResult, content_text: str) -> dict[str, Any]:
    """The Finding fields the engine can supply for one result.

    ``requires_human_review`` is true for everything except a SUPPORTED verdict: missing evidence,
    contradictions and failures always go to a person. Evidence is the guard-validated citations
    only; ``doc_id`` is the engine's document id (the backend's source_version_id if it passes
    that as doc_id, as INTEGRATION.md recommends).
    """
    span = result.claim.source_span
    relation = EVIDENCE_RELATION.get(result.verdict)
    return {
        "engine_claim_id": result.claim.claim_id,
        "original_text": span.slice(content_text),
        "span": {"start": span.start, "end": span.end},
        "verification_status": VERIFICATION_STATUS[result.verdict],
        "explanation": result.model_rationale,
        "suggested_correction": corrected_text(result, content_text),
        "requires_human_review": result.requires_human_review,
        "evidence": [
            {"doc_id": c.doc_id, "quote": c.quote, "relation": relation} for c in result.citations if relation
        ],
    }
