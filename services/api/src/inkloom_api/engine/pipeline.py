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

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from inkloom_verify.correction import ClaimCorrector
from inkloom_verify.extraction import ClaimExtractor
from inkloom_verify.providers.base import LLMProvider
from inkloom_verify.retrieval import BM25Retriever
from inkloom_verify.schemas import Claim, ClaimResult, Correction, InputContent, Verdict
from inkloom_verify.verification import ClaimVerifier, verify_claim
from sqlalchemy.orm import Session

from ..models import AuditEvent, ContentVersion, EvidenceLink, ExternalCallLog, Finding, Review
from ..result_cache import compute_cache_key, get_cached_report, materialize_cached_report, serialize_review_outcome, store_report
from ..section_diff import section_hash_for_span
from ..softening_guard import softening_issues
from ..statuses import (
    CheckType,
    EvidenceRelation,
    ExternalCallStatus,
    FindingCategory,
    ReviewState,
    Severity,
    VerificationStatus,
)
from .corpus import CorpusEntry, build_corpus, corpus_lookup  # noqa: F401 (build_corpus re-exported for routers)
from .evidence_validator import EvidenceIntegrityError, validate_all
from .provider import build_provider
from .providers.fallback import FallbackProvider

logger = logging.getLogger(__name__)

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
_CATEGORY_FOR_VERDICT = {
    Verdict.SUPPORTED: FindingCategory.SUPPORTED_CLAIM,
    Verdict.CONTRADICTED: FindingCategory.CONTRADICTED_CLAIM,
    Verdict.NOT_ENOUGH_EVIDENCE: FindingCategory.UNSUPPORTED_CLAIM,
    Verdict.ERROR: FindingCategory.ENGINE_ERROR,
}
_RELATION_FOR_VERDICT = {
    Verdict.SUPPORTED: EvidenceRelation.SUPPORTS,
    Verdict.CONTRADICTED: EvidenceRelation.CONTRADICTS,
}


def run_review(
    db: Session, review: Review, content_version: ContentVersion, corpus: list[CorpusEntry],
    confidential: bool = False,
    provider_builders: list[tuple[str, Callable[[], LLMProvider]]] | None = None,
) -> None:
    """Mutates `review` and adds `Finding`/`EvidenceLink` rows to `db`. Caller commits.

    `provider_builders` replaces the configured fallback chain (engine/provider.py) for this one
    review - used only by `scripts/seed.py` to run demo reviews through the offline scripted
    provider (engine/scripted_provider.py) with no API key. Every call is still logged to
    external_call_log exactly like a real provider's."""
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
    # A provider override (seed script) never reads or writes the cache: a scripted demo result
    # must not be replayed later as if it were a real model's answer to the same text.
    cached = get_cached_report(db, cache_key) if provider_builders is None else None
    if cached is not None:
        materialize_cached_report(db, review, cached)
        needs_review = any(f["requires_human_review"] for f in cached["findings"])
        _finish(db, review, ReviewState.NEEDS_HUMAN_REVIEW if needs_review else ReviewState.COMPLETED)
        return

    on_attempt = _make_external_call_logger(db, review, organisation_id)
    provider = (
        FallbackProvider(provider_builders, on_attempt=on_attempt)
        if provider_builders is not None
        else build_provider(confidential=confidential, on_attempt=on_attempt)
    )
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
        # Same construction as the engine's own pipeline (inkloom_verify.pipeline._run): the
        # corrector shares the provider (so its calls are logged to external_call_log like every
        # other call) and re-checks each proposal with the same verifier (recheck=True default).
        corrector = ClaimCorrector(provider, verifier)
        softener_class = load_softener_class()
        softener = softener_class(provider) if softener_class is not None else None
        content = InputContent(text=content_version.text)
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
        softening = None
        if result.verdict is Verdict.CONTRADICTED:
            result = _propose_correction(corrector, result, content, review)
        elif result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and softener is not None:
            softening = _propose_softening(softener, result, content, review)
        _write_finding(db, review, content_version, claim, result, lookup, organisation_id, softening)

    _finish(db, review, ReviewState.NEEDS_HUMAN_REVIEW if needs_human_review else ReviewState.COMPLETED)
    # Only a genuine completed analysis is cached - never a stub result or a provider/corpus
    # failure (both returned early above, before reaching here).
    if provider_builders is None:
        store_report(db, cache_key, review.id, serialize_review_outcome(db, review))


def _propose_correction(corrector: ClaimCorrector, result: ClaimResult, content: InputContent, review: Review) -> ClaimResult:
    """The engine's corrector on one CONTRADICTED result. It already turns provider failures and
    every rejected proposal into a correction attempt with no correction; anything unexpected is
    caught here too, so a correction problem can never change or drop the verdict itself."""
    try:
        return corrector.correct(result, content)
    except Exception as error:  # noqa: BLE001 - only the type name is logged, never content
        logger.error("review=%s claim=%s correction failed unexpectedly: %s",
                     review.id, result.claim.claim_id, type(error).__name__)
        return result


def load_softener_class():
    """The engine's softening step for UNVERIFIED claims, if this engine version has one.

    Not built yet: it needs a change in Member 2's engine, proposed in
    member3_backend/HANDOFF_unverified_suggestions.md as
    `inkloom_verify.softening.ClaimSoftener(provider).soften(result, content)` returning an object
    with `target_span` / `original_text` / `replacement_text`, or None. Until that module exists
    this returns None and nothing changes; once it ships, suggestions appear with no backend
    change - still behind softening_guard.py and never changing the verdict."""
    try:
        from inkloom_verify.softening import ClaimSoftener  # type: ignore[import-not-found]
    except ImportError:
        return None
    return ClaimSoftener


def _propose_softening(softener, result: ClaimResult, content: InputContent, review: Review):
    try:
        return softener.soften(result, content)
    except Exception as error:  # noqa: BLE001 - only the type name is logged, never content
        logger.error("review=%s claim=%s softening failed unexpectedly: %s",
                     review.id, result.claim.claim_id, type(error).__name__)
        return None


def claim_level_correction(text: str, claim: Claim, correction: Correction | None) -> str | None:
    """The engine proposes a targeted edit (e.g. "24 hours" -> "12 hours"); the UI replaces the
    finding's whole `original_text` with `suggested_correction`, so store the claim span with the
    edit applied. None if there is no correction or its target is not inside the claim's span.
    Also used for an unverified claim's softened wording (any object with `target_span` and
    `replacement_text`)."""
    if correction is None:
        return None
    span, target = claim.source_span, correction.target_span
    if not (span.start <= target.start <= target.end <= span.end):
        return None
    return text[span.start : target.start] + correction.replacement_text + text[target.end : span.end]


def _make_external_call_logger(db: Session, review: Review, organisation_id: uuid.UUID):
    return external_call_logger(db, organisation_id, review.request_id or "", review_id=review.id)


def external_call_logger(db: Session, organisation_id: uuid.UUID, request_id: str, review_id: uuid.UUID | None = None):
    """Phase 5 task 9: every external call, logged with provider/model/latency/error code
    only — never prompt or reply content, never credentials, never a raw provider error. Also
    used by the Trust Scorecard's evaluation runs (review_id None, request_id "eval-<run id>")."""

    def on_attempt(*, provider: str, model: str | None, status: str, latency_ms: int, error_code: str | None) -> None:
        call_status = (
            ExternalCallStatus.SUCCESS
            if status == "success"
            else _EXTERNAL_CALL_STATUS_FOR_ERROR_CODE.get(error_code or "", ExternalCallStatus.ERROR)
        )
        db.add(
            ExternalCallLog(
                organisation_id=organisation_id,
                review_id=review_id,
                provider=provider,
                model_id=model,
                request_id=request_id,
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
    # Individual-user mode: risk-based routing (Phase 9 stretch item 1) is off. The account owner
    # approves their own content, so no review is routed to a reviewer role. The column stays
    # (migration 0008) and is always written as NULL, which the UI shows as "Any approver".
    review.required_reviewer_role = None


def _write_stub_finding(db: Session, review: Review, content_version: ContentVersion, reason: str | None) -> None:
    db.add(
        Finding(
            review_id=review.id,
            category=FindingCategory.STUB.value,
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
            category=FindingCategory.ENGINE_ERROR.value,
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
    softening=None,
) -> None:
    verdict = result.verdict
    explanation = result.error.message if result.error else result.model_rationale
    suggested_correction = claim_level_correction(content_version.text, claim, result.correction)
    if verdict is Verdict.NOT_ENOUGH_EVIDENCE:
        # A safer wording for an unverified claim: from the engine's softening step, or a
        # correction the engine attached to an unverified result (both are only proposals; the
        # finding stays unverified). No evidence exists to check it against, so it must pass the
        # backend's own deterministic rules (softening_guard.py) or it is dropped.
        proposal = softening if softening is not None else result.correction
        rewritten = claim_level_correction(content_version.text, claim, proposal)
        original = claim.source_span.slice(content_version.text)
        suggested_correction = rewritten if rewritten is not None and not softening_issues(original, rewritten) else None
    elif verdict is Verdict.ERROR:
        suggested_correction = None

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
        # From the verdict AFTER backend validation: a citation that failed our own check was
        # downgraded above, so it is counted as an unsupported claim, not a contradicted one.
        category=_CATEGORY_FOR_VERDICT[verdict].value,
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
