"""A review run (one call into the engine) and its findings.

`Review.request_id` is generated and owned by the backend (CONTRACTS.md integration question 8:
"who generates request_id?" — this member does, and persists the report here so it can be
looked up later without re-running the engine).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..statuses import CheckType, EvidenceRelation, MembershipRole, ReviewState, RulesStatus, Severity, VerificationStatus, values
from .base import Base, created_at_column, updated_at_column, uuid_pk


_ROUTABLE_REVIEWER_ROLES = (MembershipRole.LEGAL_REVIEWER.value, MembershipRole.BRAND_MANAGER.value)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint(f"status IN {tuple(values(ReviewState))}", name="ck_review_status"),
        CheckConstraint(
            f"required_reviewer_role IN {_ROUTABLE_REVIEWER_ROLES} OR required_reviewer_role IS NULL",
            name="ck_review_required_reviewer_role",
        ),
        CheckConstraint(
            f"rules_status IS NULL OR rules_status IN {tuple(values(RulesStatus))}", name="ck_review_rules_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=ReviewState.DRAFT.value)
    # Engine config, carried with the review so a result is always reproducible (00_CONTEXT.md task 2).
    engine_provider: Mapped[str | None] = mapped_column(String(100))
    engine_model_id: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    engine_contract_version: Mapped[str | None] = mapped_column(String(20))
    # The request_id this backend sent to the engine (inkloom_verify.VerificationRequest.request_id).
    request_id: Mapped[str | None] = mapped_column(String(128), index=True)
    report_status: Mapped[str | None] = mapped_column(String(20))  # engine ReportStatus, once received
    error_summary: Mapped[str | None] = mapped_column(Text)  # safe message only; never raw provider errors
    # Phase 5 task 5: true when this review's findings were replayed from result_cache rather
    # than actually sent to any provider.
    served_from_cache: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Brand rules (migration 0010): whether they ran, and one check record per rule
    # (inkloom_verify.schemas.RuleCheck as JSON). Never part of the result cache.
    rules_status: Mapped[str | None] = mapped_column(String(20))
    rule_checks: Mapped[list | None] = mapped_column(JSONB)
    # Phase 9 stretch item 1 (migration 0008). Individual-user mode turned routing off: every new
    # review writes NULL here (engine/pipeline.py's _finish). Older rows may still hold a role
    # name; it is kept for history and no longer gates approval.
    required_reviewer_role: Mapped[str | None] = mapped_column(String(20))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    findings: Mapped[list["Finding"]] = relationship(back_populates="review")
    # Read-only: lets ReviewOut.from_model reach content_item_id / brand_id / title / text
    # without a second query, via the content_version's own existing `content_item` relationship
    # (models/content.py). No migration needed - the content_version_id FK already exists.
    content_version: Mapped["ContentVersion"] = relationship("ContentVersion", viewonly=True)


class Finding(Base):
    """One finding from a review. Column names match 00_CONTEXT.md task 3 exactly."""

    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint("span_end > span_start", name="ck_finding_span_order"),
        CheckConstraint(f"severity IN {tuple(values(Severity))}", name="ck_finding_severity"),
        CheckConstraint(f"check_type IN {tuple(values(CheckType))}", name="ck_finding_check_type"),
        CheckConstraint(
            f"verification_status IN {tuple(values(VerificationStatus))}", name="ck_finding_verification_status"
        ),
        CheckConstraint("scope IS NULL OR scope IN ('text', 'document')", name="ck_finding_scope"),
    )

    finding_id: Mapped[uuid.UUID] = uuid_pk("finding_id")
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str | None] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    span_end: Mapped[int] = mapped_column(Integer, nullable=False)
    check_type: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False)
    suggested_correction: Mapped[str | None] = mapped_column(Text)  # evidence-backed corrections only
    # A softened wording for an unverified claim (migration 0011): not evidence-backed, so never in
    # suggested_correction (engine CONTRACTS.md, "Mapping to Member 3's shared values").
    safer_wording: Mapped[str | None] = mapped_column(Text)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The engine's claim_id (inkloom_verify.schemas.ClaimId), kept for traceability. Opaque here.
    engine_claim_id: Mapped[str | None] = mapped_column(String(80))
    # Why a claim finding needs a person (migration 0013): the engine's ClaimReviewReason values.
    # [] when it doesn't; null on rule and stub findings and on rows written before 0013.
    review_reasons: Mapped[list | None] = mapped_column(JSONB)
    # Rule findings only (check_type "rule", migration 0010); null on claim findings.
    rule_id: Mapped[str | None] = mapped_column(String(128))  # engine ids are up to 128 chars
    rule_type: Mapped[str | None] = mapped_column(String(40))
    scope: Mapped[str | None] = mapped_column(String(10))  # "text" | "document" (something missing)
    suggestion_basis: Mapped[str | None] = mapped_column(String(30))  # "brand_rule" | "approved_document"
    created_at: Mapped[datetime] = created_at_column()

    review: Mapped[Review] = relationship(back_populates="findings")
    evidence: Mapped[list["EvidenceLink"]] = relationship(back_populates="finding")
    decisions: Mapped[list["FindingDecision"]] = relationship(order_by="FindingDecision.created_at", viewonly=True)
    comments: Mapped[list["FindingComment"]] = relationship(order_by="FindingComment.created_at", viewonly=True)


class EvidenceLink(Base):
    """Evidence for one finding. Column names match 00_CONTEXT.md task 3 exactly."""

    __tablename__ = "evidence_links"
    __table_args__ = (
        CheckConstraint(f"relation IN {tuple(values(EvidenceRelation))}", name="ck_evidence_relation"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.finding_id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL, not CASCADE: a brand_source is never hard-deleted by the app today (withdraw only
    # changes its status - Phase 7), but if it ever were, the evidence record itself should
    # survive for audit purposes with a now-dangling reference cleared, not vanish with it.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_sources.id", ondelete="SET NULL")
    )
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_versions.id", ondelete="SET NULL")
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    relation: Mapped[str] = mapped_column(String(20), nullable=False)
    # Phase 7 task 4: the hash of the section (section_diff.py) this citation's quote_span fell
    # inside, at the time the citation was made. Nullable: rows written before this column
    # existed, or a citation whose span didn't cleanly fall in one section, have no value, and
    # are simply never auto-flipped by the section-diff path (the manual withdraw still covers
    # them, since it flips every dependent unconditionally).
    cited_section_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()

    finding: Mapped[Finding] = relationship(back_populates="evidence")
    # Read-only: EvidenceLinkOut shows the cited document's title and version number. Both stay
    # None if the source row is ever gone (the FKs are ON DELETE SET NULL).
    source: Mapped["BrandSource | None"] = relationship("BrandSource", viewonly=True)
    source_version: Mapped["SourceVersion | None"] = relationship("SourceVersion", viewonly=True)


class FindingDecision(Base):
    """Per-finding Dismiss / restore (migration 0012). A separate row: the finding's verdict,
    evidence and explanation are never changed by a decision, and a dismissed finding is not
    "supported" - it was set aside by a person. The latest row says whether it is dismissed now."""

    __tablename__ = "finding_decisions"
    __table_args__ = (CheckConstraint("action IN ('dismissed', 'restored')", name="ck_finding_decision_action"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.finding_id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at_column()


class FindingComment(Base):
    """A comment on a finding (migration 0012)."""

    __tablename__ = "finding_comments"

    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.finding_id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
