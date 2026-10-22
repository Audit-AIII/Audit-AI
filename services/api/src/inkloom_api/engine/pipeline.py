"""Runs one review: extraction -> retrieval -> verification -> findings/evidence.

There is no single `VerificationRequest -> VerificationReport` function in Member 2's engine
yet (checked before writing this: `inkloom_verify` exposes `ClaimExtractor`, `BM25Retriever`,
`ClaimVerifier` and the `verify_claim` convenience function, but no end-to-end entry point). This
module is the integration that was missing, built from those pieces directly. If Member 2 later
publishes a single pipeline function, this module narrows to a thin call into it.

Rule (00_CONTEXT.md): `completed` means analysis finished, never approved, and a finding with no
evidence is `unverified`, never `false`. Never fail open — an engine or provider failure becomes
`failed` or a per-claim `ERROR` finding, never a silently-dropped claim.

Phase 4 adds: every citation is independently re-validated against this backend's own copy of
the source text before being saved (evidence_validator.py) — "the backend never trusts the
engine" (00_CONTEXT.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from inkloom_verify.extraction import ClaimExtractor
from inkloom_verify.retrieval import BM25Retriever
from inkloom_verify.schemas import Claim, ClaimResult, Verdict
from inkloom_verify.verification import ClaimVerifier, verify_claim
from sqlalchemy.orm import Session

from ..models import AuditEvent, ContentVersion, EvidenceLink, Finding, Review
from ..statuses import CheckType, EvidenceRelation, ReviewState, Severity, VerificationStatus
from .corpus import CorpusEntry, build_corpus, corpus_lookup  # noqa: F401 (build_corpus re-exported for routers)
from .evidence_validator import EvidenceIntegrityError, validate_all
from .provider import build_provider

STUB_EXPLANATION = (
    "[STUB OUTPUT] No LLM provider is configured for this backend (set OPENROUTER_API_KEY and "
    "INKLOOM_LLM_MODELS in services/api/.env). This finding is fixed placeholder content proving "
    "the review pipeline end to end; no real claim extraction or verification ran on this content."
)

INTEGRITY_REJECTED_EXPLANATION = (
    "The engine cited evidence that failed this backend's own independent check (wrong source, "
    "or a quote not actually present in that source's approved text). The citation was "
    "discarded and this claim is treated as unverified rather than trusted as-is."
)

_STATUS_FOR_VERDICT = {
    Verdict.SUPPORTED: VerificationStatus.SUPPORTED,
    Verdict.CONTRADICTED: VerificationStatus.CONTRADICTED,
    Verdict.NOT_ENOUGH_EVIDENCE: VerificationStatus.UNVERIFIED,
    Verdict.ERROR: VerificationStatus.UNVERIFIED,  # never surfaced as contradicted or false
}
_SEVERITY_FOR_VERDICT = {
    Verdict.SUPPORTED: Severity.LOW,
    Verdict.CONTRADICTED: Severity.HIGH,
    Verdict.NOT_ENOUGH_EVIDENCE: Severity.MEDIUM,
    Verdict.ERROR: Severity.MEDIUM,
}
_RELATION_FOR_VERDICT = {
    Verdict.SUPPORTED: EvidenceRelation.SUPPORTS,
    Verdict.CONTRADICTED: EvidenceRelation.CONTRADICTS,
}


def run_review(db: Session, review: Review, content_version: ContentVersion, corpus: list[CorpusEntry]) -> None:
    """Mutates `review` and adds `Finding`/`EvidenceLink` rows to `db`. Caller commits."""
    review.status = ReviewState.ANALYSING.value
    review.started_at = datetime.now(timezone.utc)

    if not corpus:
        _finish(review, ReviewState.FAILED, "This brand has no approved sources to verify content against.")
        return

    provider, unconfigured_reason = build_provider()
    if provider is None:
        review.engine_provider = "stub-unconfigured"
        _write_stub_finding(db, review, content_version, unconfigured_reason)
        _finish(review, ReviewState.NEEDS_HUMAN_REVIEW)
        return

    review.engine_provider = provider.name
    documents = [entry.document for entry in corpus]
    lookup = corpus_lookup(corpus)
    organisation_id = content_version.content_item.organisation_id

    extractor = ClaimExtractor(provider)
    extraction = extractor.extract(content_version.text)
    review.prompt_version = extraction.provenance.prompt_version
    review.engine_model_id = ",".join(sorted(extraction.provenance.models)) or None

    if not extraction.claims and not extraction.complete:
        message = "; ".join(e.message for e in extraction.errors)[:500] or "Claim extraction failed."
        _finish(review, ReviewState.FAILED, message)
        return

    retriever = BM25Retriever(documents)
    verifier = ClaimVerifier(provider, documents)

    needs_human_review = bool(extraction.errors)  # a partial extraction still needs a human look
    for claim in extraction.claims:
        # ClaimVerifier.verify() catches ProviderError itself and returns an ERROR-verdict
        # ClaimResult instead of raising, so there is nothing to catch here.
        result = verify_claim(claim, retriever, verifier)
        needs_human_review = needs_human_review or result.verdict is not Verdict.SUPPORTED
        _write_finding(db, review, content_version, claim, result, lookup, organisation_id)

    _finish(review, ReviewState.NEEDS_HUMAN_REVIEW if needs_human_review else ReviewState.COMPLETED)


def _finish(review: Review, state: ReviewState, error_summary: str | None = None) -> None:
    review.status = state.value
    review.error_summary = error_summary
    review.completed_at = datetime.now(timezone.utc)


def _write_stub_finding(db: Session, review: Review, content_version: ContentVersion, reason: str | None) -> None:
    db.add(
        Finding(
            review_id=review.id,
            category="stub",
            severity=Severity.MEDIUM.value,
            original_text=content_version.text,
            span_start=0,
            span_end=len(content_version.text),
            check_type=CheckType.SEMANTIC.value,
            explanation=f"{STUB_EXPLANATION} Reason: {reason}" if reason else STUB_EXPLANATION,
            verification_status=VerificationStatus.UNVERIFIED.value,
            requires_human_review=True,
        )
    )


def _write_finding(
    db: Session,
    review: Review,
    content_version: ContentVersion,
    claim: Claim,
    result: ClaimResult,
    lookup: dict[tuple[str, str], CorpusEntry],
    organisation_id: uuid.UUID,
) -> None:
    verdict = result.verdict
    explanation = result.error.message if result.error else result.model_rationale
    suggested_correction = result.correction.replacement_text if result.correction else None

    valid_entries: list[CorpusEntry] = []
    if verdict in (Verdict.SUPPORTED, Verdict.CONTRADICTED):
        try:
            valid_entries = validate_all(result.citations, lookup)
        except EvidenceIntegrityError as error:
            # Strict, matching CitationGuard's own policy (PROMPTS.md): one bad citation means
            # none of this finding's citations are trusted. Downgrade rather than save anything.
            _log_integrity_rejection(db, review, organisation_id, claim, error)
            verdict = Verdict.NOT_ENOUGH_EVIDENCE
            explanation = INTEGRITY_REJECTED_EXPLANATION
            suggested_correction = None

    finding = Finding(
        review_id=review.id,
        severity=_SEVERITY_FOR_VERDICT[verdict].value,
        original_text=claim.source_span.slice(content_version.text),
        span_start=claim.source_span.start,
        span_end=claim.source_span.end,
        check_type=CheckType.RETRIEVAL.value,
        explanation=explanation,
        verification_status=_STATUS_FOR_VERDICT[verdict].value,
        suggested_correction=suggested_correction,
        requires_human_review=verdict is not Verdict.SUPPORTED,
        engine_claim_id=claim.claim_id,
    )
    db.add(finding)
    db.flush()  # assigns finding.finding_id, needed for the evidence rows' FK

    relation = _RELATION_FOR_VERDICT.get(verdict)
    if relation is None:
        return  # NOT_ENOUGH_EVIDENCE / ERROR never carry citations (engine contract)
    for citation, entry in zip(result.citations, valid_entries):
        db.add(
            EvidenceLink(
                finding_id=finding.finding_id,
                source_id=entry.brand_source_id,
                source_version_id=entry.source_version_id,
                quote=citation.quote,
                relation=relation.value,
            )
        )


def _log_integrity_rejection(
    db: Session, review: Review, organisation_id: uuid.UUID, claim: Claim, error: EvidenceIntegrityError
) -> None:
    db.add(
        AuditEvent(
            organisation_id=organisation_id,
            actor_user_id=None,  # system-detected, not a user action
            event_type="evidence.integrity_rejected",
            entity_type="review",
            entity_id=str(review.id),
            details={
                "code": error.code.value,
                "claim_id": claim.claim_id,
                "doc_id": error.citation.doc_id,
                "passage_id": error.citation.passage_id,
            },
            request_id=review.request_id,
        )
    )
