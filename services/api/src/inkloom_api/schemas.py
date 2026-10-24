"""API response DTOs. Never return SQLAlchemy models directly: these control exactly what
leaves the process (no password_hash, no other tenants' rows reachable by relationship)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .intent_lock_guard import breaks_locks


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(_Out):
    id: uuid.UUID
    email: str
    display_name: str | None


class OrganisationOut(_Out):
    id: uuid.UUID
    name: str
    slug: str


class SessionInfo(BaseModel):
    user: UserOut
    organisation: OrganisationOut
    role: str


class LoginResponse(SessionInfo):
    access_token: str
    token_type: str = "bearer"
    # None by default so a response built before this field existed (there isn't one today, but
    # future replay/cache paths might) still validates. Login and register both set the real
    # value explicitly.
    expires_in: int | None = None


class BrandOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    approved_source_count: int
    created_at: datetime
    # Dashboard fields (additive). Real counts only - zero / null when the brand has no reviews.
    # "Open" = waiting for the user's decision (review_queries.py has the one definition).
    review_count: int = 0
    open_review_count: int = 0
    last_review_at: datetime | None = None


class RegisterResponse(LoginResponse):
    """POST /api/auth/register: everything a login gets, plus the brand created in the same
    transaction - the caller never needs to look up a brand_id separately."""

    brand: BrandOut


class BrandSourceOut(BaseModel):
    id: uuid.UUID
    brand_profile_id: uuid.UUID
    title: str
    status: str
    sensitivity: str
    source_type: str | None
    latest_version: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, source) -> "BrandSourceOut":
        versions = sorted(source.versions, key=lambda v: v.version_number)
        return cls(
            id=source.id,
            brand_profile_id=source.brand_profile_id,
            title=source.title,
            status=source.status,
            sensitivity=source.sensitivity,
            source_type=source.source_type,
            latest_version=versions[-1].version_number if versions else None,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )


# --- Reviews / findings / evidence: contract/schemas/review.schema.json, finding.schema.json --


class SpanOut(BaseModel):
    start: int
    end: int


class EvidenceLinkOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID | None
    source_version_id: uuid.UUID | None
    quote: str
    relation: str
    # Additive: which approved document (and which version of it) the quote came from.
    source_title: str | None = None
    source_version_number: int | None = None

    @classmethod
    def from_model(cls, evidence) -> "EvidenceLinkOut":
        return cls(
            id=evidence.id,
            source_id=evidence.source_id,
            source_version_id=evidence.source_version_id,
            quote=evidence.quote,
            relation=evidence.relation,
            source_title=evidence.source.title if evidence.source is not None else None,
            source_version_number=(
                evidence.source_version.version_number if evidence.source_version is not None else None
            ),
        )


class DismissalOut(BaseModel):
    """Set while a finding is dismissed. Dismissed is not "supported": the verdict is unchanged."""

    by_user_id: uuid.UUID | None
    at: datetime
    note: str | None


class FindingOut(BaseModel):
    finding_id: uuid.UUID
    category: str | None
    severity: str
    original_text: str
    span: SpanOut
    check_type: str
    explanation: str | None
    verification_status: str
    suggested_correction: str | None
    requires_human_review: bool
    evidence: list[EvidenceLinkOut]
    # Unverified claims only: a softened wording, NOT evidence-backed (UI: "Safer wording, not
    # evidence-backed"). Kept apart from suggested_correction, which is evidence-backed only.
    safer_wording: str | None = None
    # Claim findings: why a person must decide (the engine's ClaimReviewReason values: contradicted,
    # not_enough_evidence, error, weak_evidence, below_policy_strength, compound_under_cited);
    # [] when no review is needed. Null on rule and stub findings and on older rows.
    review_reasons: list[str] | None = None
    # Rule findings only (check_type "rule"; services/verification/RULES_HANDOFF.md section 7),
    # null on claim findings. Defaults keep older idempotency replays parsing.
    rule_id: str | None = None
    rule_type: str | None = None
    scope: str | None = None  # "text": the span is the offending text; "document": something is missing
    suggestion_basis: str | None = None  # "brand_rule" | "approved_document"
    source_ids: list[uuid.UUID] | None = None  # the approved documents a rule is quoted from
    # Phase 7 (all additive). True when a stored suggestion would remove a phrase the writer locked
    # after the review ran: it is withheld (re-run to get one that keeps the locks).
    withheld_by_intent_lock: bool = False
    dismissal: DismissalOut | None = None
    comment_count: int = 0

    @classmethod
    def from_model(cls, finding, text: str | None = None, locks: list[str] | None = None) -> "FindingOut":
        suggested, safer, withheld = finding.suggested_correction, finding.safer_wording, False
        if text is not None and locks:
            if breaks_locks(text, finding.span_start, finding.span_end, suggested, locks):
                suggested, withheld = None, True
            if breaks_locks(text, finding.span_start, finding.span_end, safer, locks):
                safer, withheld = None, True
        latest = finding.decisions[-1] if finding.decisions else None
        return cls(
            finding_id=finding.finding_id,
            category=finding.category,
            severity=finding.severity,
            original_text=finding.original_text,
            span=SpanOut(start=finding.span_start, end=finding.span_end),
            check_type=finding.check_type,
            explanation=finding.explanation,
            verification_status=finding.verification_status,
            suggested_correction=suggested,
            requires_human_review=finding.requires_human_review,
            evidence=[EvidenceLinkOut.from_model(e) for e in finding.evidence],
            safer_wording=safer,
            review_reasons=finding.review_reasons,
            withheld_by_intent_lock=withheld,
            dismissal=(
                DismissalOut(by_user_id=latest.actor_user_id, at=latest.created_at, note=latest.note)
                if latest is not None and latest.action == "dismissed" else None
            ),
            comment_count=len(finding.comments),
            rule_id=finding.rule_id,
            rule_type=finding.rule_type,
            scope=finding.scope,
            suggestion_basis=finding.suggestion_basis,
            source_ids=(
                [e.source_id for e in finding.evidence if e.source_id is not None]
                if finding.check_type == "rule" else None
            ),
        )


class RuleCheckOut(BaseModel):
    """One rule's outcome (inkloom_verify.schemas.RuleCheck): passed, violated, not_checkable (the
    draft lacks what the check needs - show "not checked", never "passed") or error."""

    rule_id: str
    rule_type: str
    category: str
    status: str
    findings: int
    reason: str | None


class EngineInfoOut(BaseModel):
    provider: str | None
    model_id: str | None
    prompt_version: str | None
    contract_version: str | None


class ReviewOut(BaseModel):
    id: uuid.UUID
    content_version_id: uuid.UUID
    status: str
    report_status: str | None
    engine: EngineInfoOut | None
    error_summary: str | None
    served_from_cache: bool
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    findings: list[FindingOut]
    # Kept for the UI's existing contract (it shows null as "Any approver"). Individual-user mode
    # turned risk-based routing off, so every new review has null here; an older review may still
    # carry "legal_reviewer"/"brand_manager", which no longer restricts who can approve it.
    required_reviewer_role: str | None
    # Self-serve onboarding: default None so an idempotency replay recorded before these fields
    # existed still parses (ReviewOut(**replay) in routers/reviews.py). Filled from
    # review.content_version (Review.content_version, a viewonly relationship) and that version's
    # own existing `content_item` relationship - no new query, no migration.
    content_item_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    title: str | None = None
    version_number: int | None = None
    text: str | None = None
    brand_name: str | None = None  # additive; via content_item.brand_profile (viewonly)
    # Brand rules (migration 0010): complete | incomplete | not_applied, null on older reviews;
    # and one check record per rule (null when the rules did not run).
    rules_status: str | None = None
    rule_checks: list[RuleCheckOut] | None = None
    locked_phrases: list[str] | None = None  # Intent-lock list of the reviewed content version

    @classmethod
    def from_model(cls, review) -> "ReviewOut":
        engine = (
            EngineInfoOut(
                provider=review.engine_provider,
                model_id=review.engine_model_id,
                prompt_version=review.prompt_version,
                contract_version=review.engine_contract_version,
            )
            if review.engine_provider
            else None
        )
        content_version = review.content_version
        content_item = content_version.content_item if content_version is not None else None
        locks = list(content_version.locked_phrases or []) if content_version is not None else []
        return cls(
            id=review.id,
            content_version_id=review.content_version_id,
            status=review.status,
            report_status=review.report_status,
            engine=engine,
            error_summary=review.error_summary,
            served_from_cache=review.served_from_cache,
            started_at=review.started_at,
            completed_at=review.completed_at,
            created_at=review.created_at,
            updated_at=review.updated_at,
            findings=[
                FindingOut.from_model(f, content_version.text if content_version is not None else None, locks)
                for f in review.findings
            ],
            required_reviewer_role=review.required_reviewer_role,
            content_item_id=content_version.content_item_id if content_version is not None else None,
            brand_id=content_item.brand_profile_id if content_item is not None else None,
            title=content_item.title if content_item is not None else None,
            version_number=content_version.version_number if content_version is not None else None,
            text=content_version.text if content_version is not None else None,
            brand_name=(
                content_item.brand_profile.name
                if content_item is not None and content_item.brand_profile is not None
                else None
            ),
            rules_status=review.rules_status,
            rule_checks=review.rule_checks,
            locked_phrases=locks if content_version is not None else None,
        )


# --- Phase 6: versioning, approval, audit --------------------------------------------------


class LockWarningOut(BaseModel):
    """A locked phrase the user's own edit dropped (inkloom_verify.intent_lock): a warning only."""

    phrase: str
    occurrences_before: int
    occurrences_after: int


class NewVersionResponse(BaseModel):
    content_version_id: uuid.UUID
    version_number: int
    is_current: bool
    review: ReviewOut
    # Intent-lock, hand-written edits: WARN, never block (HANDOFF_STEPS_6_8.md step 4). Locked
    # phrases this edit keeps fewer times than the previous version did; the version is saved.
    lock_warnings: list[LockWarningOut] = []


class ApprovalEventOut(BaseModel):
    id: uuid.UUID
    content_version_id: uuid.UUID
    version_number: int | None = None  # only set when the caller has the version loaded already
    action: str
    actor_user_id: uuid.UUID
    note: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, event, version_number: int | None = None) -> "ApprovalEventOut":
        return cls(
            id=event.id, content_version_id=event.content_version_id, version_number=version_number,
            action=event.action, actor_user_id=event.actor_user_id, note=event.note, created_at=event.created_at,
        )


class ReviewSummaryOut(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime

    @classmethod
    def from_model(cls, review) -> "ReviewSummaryOut":
        return cls(id=review.id, status=review.status, created_at=review.created_at)


class FindingEventOut(BaseModel):
    """Something the user did to one finding of this version's reviews (Dismiss, restore, a
    comment). `note` is the user's own Dismiss/restore note; a comment's text is never here
    (GET /api/findings/{id}/comments has it)."""

    event_type: str  # "finding.dismissed" | "finding.restored" | "finding.commented"
    finding_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    created_at: datetime
    note: str | None


class ContentVersionHistoryOut(BaseModel):
    id: uuid.UUID
    version_number: int
    is_current: bool
    created_by: uuid.UUID | None
    created_at: datetime
    reviews: list[ReviewSummaryOut]
    decisions: list[ApprovalEventOut]
    finding_events: list[FindingEventOut] = []  # additive; oldest first


class ContentHistoryOut(BaseModel):
    content_item_id: uuid.UUID
    title: str
    versions: list[ContentVersionHistoryOut]


# --- Phase 7: source lifecycle / InkWatch --------------------------------------------------


class FlippedDependentOut(BaseModel):
    content_version_id: uuid.UUID
    review_id: uuid.UUID


class WithdrawSourceResponse(BaseModel):
    source: BrandSourceOut
    reason: str
    flipped: list[FlippedDependentOut]


class NewSourceVersionResponse(BaseModel):
    source: BrandSourceOut
    version_number: int
    flipped: list[FlippedDependentOut]
