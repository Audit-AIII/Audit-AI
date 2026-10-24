"""Phase 7 tasks 2-4: dependency lookup, the manual "withdraw source" action, and the automatic
section-diff that narrows it.

Task 2's query: every `Finding`'s `EvidenceLink.source_id` already names the brand source it
cited (Phase 4), so finding every content version that depends on a source is a join through
`EvidenceLink -> Finding -> Review -> ContentVersion` — no new columns needed, task 1's "keep
every source version and what each historical review used" was already true from Phase 1/4.

Task 3 scopes "dependents" to the Goal's wording exactly: "every **approved** item that relied
on it" - a content version whose latest review never reached `approved` has nothing to
re-flag; flipping it to `source_changed` would be reporting drift on a decision that was never
made. `withdraw_source` flips every such dependent unconditionally (manual, built first, per the
doc's own sequencing).

Task 4 narrows that: `apply_new_version_diff` only flips a dependent whose evidence actually
cited a section (section_diff.py) that is no longer present, verbatim, anywhere in the new
version - a dependent that cited an unrelated, unchanged part of the document is left alone.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from .audit import log_audit_event
from .models import BrandSource, ContentVersion, EvidenceLink, Finding, Review, SourceVersion
from .statuses import ReviewState


def dependent_content_version_ids(db: Session, brand_source_id: uuid.UUID) -> list[uuid.UUID]:
    """Every content_version_id whose evidence cites this brand source, at any version of it."""
    rows = (
        db.query(ContentVersion.id)
        .join(Review, Review.content_version_id == ContentVersion.id)
        .join(Finding, Finding.review_id == Review.id)
        .join(EvidenceLink, EvidenceLink.finding_id == Finding.finding_id)
        .filter(EvidenceLink.source_id == brand_source_id)
        .distinct()
        .all()
    )
    return [row[0] for row in rows]


def latest_review_for(db: Session, content_version_id: uuid.UUID) -> Review | None:
    return (
        db.query(Review)
        .filter_by(content_version_id=content_version_id)
        .order_by(Review.created_at.desc())
        .first()
    )


def _flip_to_source_changed(
    db: Session,
    review: Review,
    content_version_id: uuid.UUID,
    organisation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str,
    source_id: uuid.UUID,
) -> None:
    review.status = ReviewState.SOURCE_CHANGED.value
    log_audit_event(
        db,
        organisation_id=organisation_id,
        actor_user_id=actor_user_id,
        event_type="content_version.source_changed",
        entity_type="content_version",
        entity_id=content_version_id,
        details={"reason": reason, "source_id": str(source_id), "review_id": str(review.id)},
    )


def withdraw_source(
    db: Session,
    source: BrandSource,
    new_status: str,
    reason: str,
    organisation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> list[dict]:
    """Sets `source.status`, flips every currently-approved dependent to `source_changed`, and
    logs one audit event per flipped item (task 3: "writes audit events"; task 5's "notification
    record" - the reviewer queue is meant to read these same events, not a separate table).
    Returns `[{"content_version_id", "review_id"}, ...]` for the flipped items."""
    source.status = new_status
    flipped: list[dict] = []
    for content_version_id in dependent_content_version_ids(db, source.id):
        review = latest_review_for(db, content_version_id)
        if review is None or review.status != ReviewState.APPROVED.value:
            continue  # never approved, or already in some other state - nothing to re-flag
        _flip_to_source_changed(
            db, review, content_version_id, organisation_id, actor_user_id, reason, source.id
        )
        flipped.append({"content_version_id": content_version_id, "review_id": review.id})
    return flipped


def apply_new_version_diff(
    db: Session,
    source: BrandSource,
    new_version: SourceVersion,
    organisation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> list[dict]:
    """Task 4: only flips a dependent whose evidence cited a section that didn't survive,
    verbatim, into `new_version`. Reason is generated, not supplied - this path has no human
    typing one in."""
    new_hashes = set(new_version.section_hashes or [])
    flipped: list[dict] = []
    for content_version_id in dependent_content_version_ids(db, source.id):
        review = latest_review_for(db, content_version_id)
        if review is None or review.status != ReviewState.APPROVED.value:
            continue

        cited_hashes = (
            db.query(EvidenceLink.cited_section_hash)
            .join(Finding, Finding.finding_id == EvidenceLink.finding_id)
            .filter(Finding.review_id == review.id, EvidenceLink.source_id == source.id)
            .filter(EvidenceLink.cited_section_hash.isnot(None))
            .all()
        )
        if not any(h not in new_hashes for (h,) in cited_hashes):
            continue  # every section this review actually cited is still present, unchanged

        _flip_to_source_changed(
            db,
            review,
            content_version_id,
            organisation_id,
            actor_user_id,
            reason=f"a cited section of source {source.id} changed in a new version",
            source_id=source.id,
        )
        flipped.append({"content_version_id": content_version_id, "review_id": review.id})
    return flipped
