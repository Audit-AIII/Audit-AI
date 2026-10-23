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

from ..models import AuditEvent, ContentVersion, EvidenceLink, ExternalCallLog, Finding, Review
from ..result_cache import compute_cache_key, get_cached_report, materialize_cached_report, serialize_review_outcome, store_report
from ..section_diff import section_hash_for_span
from ..statuses import (
    CheckType,
    EvidenceRelation,
    ExternalCallStatus,
    MembershipRole,
    ReviewState,
    Severity,
    VerificationStatus,
)
from .corpus import CorpusEntry, build_corpus, corpus_lookup  # noqa: F401 (build_corpus re-exported for routers)
from .evidence_validator import EvidenceIntegrityError, validate_all
from .provider import build_provider

STUB_EXPLANATION = (
    "[STUB OUTPUT] No LLM provider is configured for this backend (none of GEMINI_API_KEY, "
    "GROQ_API_KEY, OPENROUTER_API_KEY or OLLAMA_MODEL are set in services/api/.env). This "
    "finding is fixed placeholder content proving the review pipeline end to end; no real "
    "claim extraction or verification ran on this content."
)

_EXTERNAL_CALL_STATUS_FOR_ERROR_CODE = {
    "PROVIDER_TIMEOUT": ExternalCallStatus.TIMEOUT,
    "PROVIDER_RATE_LIMITED": ExternalCallStatus.RATE_LIMITED,
}

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


def run_review(
    db: Session, review: Review, content_version: ContentVersion, corpus: list[CorpusEntry],
    confidential: bool = False,
) -> None:
    """Mutates `review` and adds `Finding`/`EvidenceLink` rows to `db`. Caller commits."""
    review.status = ReviewState.ANALYSING.value
    review.started_at = datetime.now(timezone.utc)

    if not corpus:
        _finish(db, review, ReviewState.FAILED, "This brand has no approved sources to verify content against.")
        return

    organisation_id = content_version.content_item.organisation_id

    # Phase 5 task 5: a cache hit never touches a provider at all - zero external_call_log
    # rows, and (combined with task 8 below) a confidential source cached from an earlier
    # Ollama-only run stays confidential; nothing here re-routes it to the cloud.
    cache_key = compute_cache_key(organisation_id, content_version, corpus)
    cached = get_cached_report(db, cache_key)
    if cached is not None:
        materialize_cached_report(db, review, cached)
        needs_review = any(f["requires_human_review"] for f in cached["findings"])
        _finish(db, review, ReviewState.NEEDS_HUMAN_REVIEW if needs_review else ReviewState.COMPLETED)
        return

    provider = build_provider(confidential=confidential, on_attempt=_make_external_call_logger(db, review, organisation_id))
    if not provider.configured_providers:
        review.engine_provider = "stub-unconfigured"
        if confidential:
            reason = "a confidential source is in scope, so only local Ollama was tried, and it is not configured (OLLAMA_MODEL unset)"
        else:
            reason = f"none configured (tried: {', '.join(provider.unconfigured)})"
        _write_stub_finding(db, review, content_version, reason)
        _finish(db, review, ReviewState.NEEDS_HUMAN_REVIEW)
        return

    review.engine_provider = provider.name
    documents = [entry.document for entry in corpus]
    lookup = corpus_lookup(corpus)

    extractor = ClaimExtractor(provider)
    extraction = extractor.extract(content_version.text)
    review.prompt_version = extraction.provenance.prompt_version
    review.engine_model_id = ",".join(sorted(extraction.provenance.models)) or None

    if not extraction.claims and not extraction.complete:
        message = "; ".join(e.message for e in extraction.errors)[:500] or "Claim extraction failed."
        _finish(db, review, ReviewState.FAILED, message)
        return

    try:
        retriever = BM25Retriever(documents)
        verifier = ClaimVerifier(provider, documents)
    except Exception as error:  # e.g. RetrievalError/RetrievalLimitError on a malformed corpus
        _finish(db, review, ReviewState.FAILED, f"Could not prepare the reference corpus: {type(error).__name__}"[:500])
        return

    needs_human_review = bool(extraction.errors)  # a partial extraction still needs a human look
    for claim in extraction.claims:
        try:
            # ClaimVerifier.verify() already catches ProviderError itself and returns an
            # ERROR-verdict ClaimResult rather than raising, so reaching the except below means
            # something unexpected - a bug, or engine output malformed in a way its own guards
            # missed (Phase 8 checklist: "invalid schema is rejected"). One bad claim must never
            # crash the whole request or silently drop the claim.
            result = verify_claim(claim, retriever, verifier)
        except Exception as error:
            needs_human_review = True
            _write_unexpected_error_finding(db, review, content_version, claim, error)
            continue
        needs_human_review = needs_human_review or result.verdict is not Verdict.SUPPORTED
        _write_finding(db, review, content_version, claim, result, lookup, organisation_id)

    _finish(db, review, ReviewState.NEEDS_HUMAN_REVIEW if needs_human_review else ReviewState.COMPLETED)
    # Only a genuine completed analysis is cached - never a stub result or a provider/corpus
    # failure (both returned early above, before reaching here).
    store_report(db, cache_key, review.id, serialize_review_outcome(db, review))


def _make_external_call_logger(db: Session, review: Review, organisation_id: uuid.UUID):
    """Phase 5 task 9: every external call, logged with provider/model/latency/error code
    only — never prompt or reply content, never credentials, never a raw provider error."""

    def on_attempt(*, provider: str, model: str | None, status: str, latency_ms: int, error_code: str | None) -> None:
        call_status = (
            ExternalCallStatus.SUCCESS
            if status == "success"
            else _EXTERNAL_CALL_STATUS_FOR_ERROR_CODE.get(error_code or "", ExternalCallStatus.ERROR)
        )
        db.add(
            ExternalCallLog(
                organisation_id=organisation_id,
                review_id=review.id,
                provider=provider,
                model_id=model,
                request_id=review.request_id or "",
                status=call_status.value,
                latency_ms=latency_ms,
                error_code=error_code,
            )
        )

    return on_attempt


def _finish(db: Session, review: Review, state: ReviewState, error_summary: str | None = None) -> None:
    review.status = state.value
    review.error_summary = error_summary
    review.completed_at = datetime.now(timezone.utc)
    if state in (ReviewState.COMPLETED, ReviewState.NEEDS_HUMAN_REVIEW):
        # Phase 9 stretch item 1: only a decidable outcome has findings worth routing on - a
        # FAILED review (no corpus, extraction failure, etc.) never reaches here with any.
        review.required_reviewer_role = _compute_required_reviewer_role(db, review)


_HIGH_RISK_SEVERITIES = frozenset({Severity.HIGH.value, Severity.CRITICAL.value})


def _compute_required_reviewer_role(db: Session, review: Review) -> str:
    """Deterministic risk-based routing (Phase 9 stretch item 1): any high/critical finding
    routes to the legal reviewer; everything else (including zero findings) is a clean item for
    the brand manager's one-click sign-off. Queried directly rather than via `review.findings`
    so it sees exactly what was just flushed, regardless of how those rows were added."""
    severities = db.query(Finding.severity).filter_by(review_id=review.id).all()
    high_risk = any(severity in _HIGH_RISK_SEVERITIES for (severity,) in severities)
    return (MembershipRole.LEGAL_REVIEWER if high_risk else MembershipRole.BRAND_MANAGER).value


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


def _write_unexpected_error_finding(
    db: Session, review: Review, content_version: ContentVersion, claim: Claim, error: Exception
) -> None:
    db.add(
        Finding(
            review_id=review.id,
            severity=Severity.MEDIUM.value,
            original_text=claim.source_span.slice(content_version.text),
            span_start=claim.source_span.start,
            span_end=claim.source_span.end,
            check_type=CheckType.RETRIEVAL.value,
            explanation=(
                f"Verification failed unexpectedly for this claim ({type(error).__name__}); "
                "treated as unverified rather than trusted."
            ),
            verification_status=VerificationStatus.UNVERIFIED.value,
            requires_human_review=True,
            engine_claim_id=claim.claim_id,
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
                # Phase 7 task 4: which section this citation came from, so a future source
                # version upload can tell whether that exact section survived unchanged.
                cited_section_hash=section_hash_for_span(entry.document, citation.quote_span),
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
