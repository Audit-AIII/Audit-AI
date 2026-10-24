"""API response DTOs. Never return SQLAlchemy models directly: these control exactly what
leaves the process (no password_hash, no other tenants' rows reachable by relationship)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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

    @classmethod
    def from_model(cls, finding) -> "FindingOut":
        return cls(
            finding_id=finding.finding_id,
            category=finding.category,
            severity=finding.severity,
            original_text=finding.original_text,
            span=SpanOut(start=finding.span_start, end=finding.span_end),
            check_type=finding.check_type,
            explanation=finding.explanation,
            verification_status=finding.verification_status,
            suggested_correction=finding.suggested_correction,
            requires_human_review=finding.requires_human_review,
            evidence=[EvidenceLinkOut.from_model(e) for e in finding.evidence],
        )


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
            findings=[FindingOut.from_model(f) for f in review.findings],
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
        )


# --- Phase 6: versioning, approval, audit --------------------------------------------------


class NewVersionResponse(BaseModel):
    content_version_id: uuid.UUID
    version_number: int
    is_current: bool
    review: ReviewOut


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


class ContentVersionHistoryOut(BaseModel):
    id: uuid.UUID
    version_number: int
    is_current: bool
    created_by: uuid.UUID | None
    created_at: datetime
    reviews: list[ReviewSummaryOut]
    decisions: list[ApprovalEventOut]


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
