"""Shared, tenant-scoped review queries for the dashboard, the review queue and analytics.

"Waiting for the user's decision" has exactly one definition, used everywhere a count or an age
of open reviews is shown (BrandOut.open_review_count, analytics' queue_age_minutes): the latest
review of a content item's *current* version, in a decidable state (`completed` or
`needs_human_review`). A review left behind on an older version, or superseded by a rerun of the
same version, is not counted - approving it would be refused as stale, so it isn't waiting on
anyone.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from .approval_rules import DECIDABLE_STATES
from .auth.dependencies import AuthContext
from .auth.permissions import Permission, allowed_review_actions, role_has_permission
from .config import get_settings
from .models import ContentItem, ContentVersion, Membership, Review
from .schemas import ReviewOut
from .workflow import effective_assessment


def reviews_in_organisation(organisation_id: uuid.UUID):
    """`SELECT reviews ...` joined to their content item, restricted to one account. Every query
    in this module starts here, so tenant scope can't be forgotten by a caller."""
    return (
        select(Review)
        .join(ContentVersion, ContentVersion.id == Review.content_version_id)
        .join(ContentItem, ContentItem.id == ContentVersion.content_item_id)
        .where(ContentItem.organisation_id == organisation_id)
    )


def _latest_review_per_version():
    return (
        select(Review.content_version_id, func.max(Review.created_at).label("latest_at"))
        .group_by(Review.content_version_id)
        .subquery()
    )


def awaiting_decision_condition():
    """A WHERE clause (for a query built on `reviews_in_organisation`) selecting only reviews
    waiting for the user's decision - see the module docstring."""
    latest = _latest_review_per_version()
    is_latest = (
        select(latest.c.content_version_id)
        .where(
            and_(
                latest.c.content_version_id == Review.content_version_id,
                latest.c.latest_at == Review.created_at,
            )
        )
        .exists()
    )
    return and_(ContentVersion.is_current.is_(True), Review.status.in_(DECIDABLE_STATES), is_latest)


def brand_review_stats(db: Session, organisation_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    """{brand_id: {"review_count", "open_review_count", "last_review_at"}} for every brand in the
    account that has at least one review - two GROUP BY queries, not one query per brand."""
    totals = db.execute(
        reviews_in_organisation(organisation_id)
        .with_only_columns(
            ContentItem.brand_profile_id, func.count(Review.id), func.max(Review.created_at)
        )
        .group_by(ContentItem.brand_profile_id)
    ).all()
    open_counts = dict(
        db.execute(
            reviews_in_organisation(organisation_id)
            .where(awaiting_decision_condition())
            .with_only_columns(ContentItem.brand_profile_id, func.count(Review.id))
            .group_by(ContentItem.brand_profile_id)
        ).all()
    )
    return {
        brand_id: {
            "review_count": count,
            "open_review_count": open_counts.get(brand_id, 0),
            "last_review_at": last,
        }
        for brand_id, count, last in totals
        if brand_id is not None
    }


def latest_review_ids(db: Session, content_version_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The id of the newest review of each of these versions - the one a decision acts on
    (content_versions router: latest by `created_at`). One query for any number of versions."""
    if not content_version_ids:
        return set()
    rows = db.execute(
        select(Review.id)
        .where(Review.content_version_id.in_(content_version_ids))
        .distinct(Review.content_version_id)
        .order_by(Review.content_version_id, Review.created_at.desc(), Review.id.desc())
    ).all()
    return {row.id for row in rows}


def review_outs(db: Session, auth: AuthContext, reviews: list[Review]) -> list[ReviewOut]:
    """`ReviewOut`s with `allowed_actions` for the caller. Every route returning a review builds
    it here, so no route can forget the field or compute it differently."""
    latest = latest_review_ids(db, {r.content_version_id for r in reviews})
    members = (
        db.query(Membership.user_id, Membership.role)
        .filter(Membership.organisation_id == auth.organisation_id, Membership.is_active.is_(True))
        .all()
    )
    approvers = {u for u, role in members if role_has_permission(role, Permission.APPROVE)}
    reviewers = {u for u, role in members if role_has_permission(role, Permission.MARK_REVIEWED)}
    # D1 / D6: the caller may sign off or review their own work only while nobody else could.
    self_approval_allowed = not (approvers - {auth.user_id})
    self_review_allowed = not (reviewers - {auth.user_id})
    # P4: a solo approver's approval also stands in for the review a risky draft needs.
    solo_review_shortcut = (
        get_settings().solo_review_shortcut
        and self_review_allowed
        and self_approval_allowed
        and role_has_permission(auth.role, Permission.MARK_REVIEWED)
        and role_has_permission(auth.role, Permission.APPROVE)
    )
    outs = []
    for review in reviews:
        version = review.content_version
        item = version.content_item
        routing = None
        if review.id in latest and version.is_current:
            fresh = effective_assessment(item, review)
            routing = fresh if fresh is not None and not fresh.blocked else None
        actions = allowed_review_actions(
            auth.role,
            auth.user_id,
            item,
            review.status,
            is_latest_review=review.id in latest,
            is_current_version=version.is_current,
            content_version=version,
            self_approval_allowed=self_approval_allowed,
            self_review_allowed=self_review_allowed,
            risk_level=routing.level if routing else None,
            required_reviewer_role=routing.required_reviewer_role if routing else None,
            solo_review_shortcut=solo_review_shortcut,
        )
        approval_mode = "team" if approvers - {item.created_by} else "self"
        outs.append(
            ReviewOut.from_model(
                review,
                allowed_actions=actions,
                is_current_version=version.is_current,
                approval_mode=approval_mode,
                routing=routing,
                member_count=len(members),
            )
        )
    return outs


def review_out(db: Session, auth: AuthContext, review: Review) -> ReviewOut:
    return review_outs(db, auth, [review])[0]
