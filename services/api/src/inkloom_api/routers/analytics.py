"""GET /api/analytics/brand-risk - the Insights page (frontend lib/additions/analytics.ts,
`BrandRisk`).

Every number is computed from real rows of the caller's own account, for one brand, over the
reviews created in the last `days` days. Nothing is estimated, and the model's self-reported
confidence is never used. When there is nothing to measure the answer says so: an empty list,
nulls and `sample_size: 0` - never a made-up zero.

Definitions (also in services/api/API.md):
- sample_size: reviews created in the period.
- top_categories: finding counts by `category` across those reviews, excluding "stub",
  "supported_claim" and uncategorised findings; descending, top 6.
- median_turnaround_minutes: review created -> its first decision (approve / request changes /
  reject), over the period's reviews that have one. null if none were decided.
- re_review_rate: of the content items those reviews belong to, the share with 2+ versions.
  null if there are no items.
- queue_age_minutes: now - created, for the period's reviews still waiting for the user's
  decision (review_queries.awaiting_decision_condition). median and oldest; null if none.
"""

from __future__ import annotations

import statistics
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.dependencies import AuthContext, get_current_membership
from ..db import get_db
from ..models import ApprovalEvent, ContentItem, ContentVersion, Finding, Review
from ..review_queries import awaiting_decision_condition, reviews_in_organisation
from ..statuses import FindingCategory
from ..tenancy import get_brand_profile_or_404

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

TOP_CATEGORIES = 6
_EXCLUDED_CATEGORIES = (FindingCategory.STUB.value, FindingCategory.SUPPORTED_CLAIM.value)


class CategoryCount(BaseModel):
    category: str
    count: int


class QueueAge(BaseModel):
    median: float | None
    oldest: float | None


class BrandRiskOut(BaseModel):
    top_categories: list[CategoryCount]
    median_turnaround_minutes: float | None
    re_review_rate: float | None
    queue_age_minutes: QueueAge
    sample_size: int


def _minutes(delta: timedelta) -> float:
    return delta.total_seconds() / 60


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


@router.get("/brand-risk", response_model=BrandRiskOut)
def brand_risk(
    brand_id: uuid.UUID | None = None,
    days: int = Query(default=30, ge=1, le=365),
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> BrandRiskOut:
    """`brand_id` is what the Insights page always sends; another account's brand is a 404.
    Without it, the same numbers are computed over every brand in the caller's account."""
    if brand_id is not None:
        get_brand_profile_or_404(db, auth.organisation_id, brand_id)
    now = datetime.now(timezone.utc)

    period = reviews_in_organisation(auth.organisation_id).where(Review.created_at >= now - timedelta(days=days))
    if brand_id is not None:
        period = period.where(ContentItem.brand_profile_id == brand_id)
    period_ids = period.with_only_columns(Review.id).scalar_subquery()

    sample_size = db.scalar(period.with_only_columns(func.count(Review.id))) or 0

    category_rows = db.execute(
        select(Finding.category, func.count(Finding.finding_id))
        .where(
            Finding.review_id.in_(period_ids),
            Finding.category.isnot(None),
            Finding.category.notin_(_EXCLUDED_CATEGORIES),
        )
        .group_by(Finding.category)
        .order_by(func.count(Finding.finding_id).desc(), Finding.category)
        .limit(TOP_CATEGORIES)
    ).all()

    first_decisions = db.execute(
        select(Review.created_at, func.min(ApprovalEvent.created_at))
        .join(ApprovalEvent, ApprovalEvent.review_id == Review.id)
        .where(Review.id.in_(period_ids))
        .group_by(Review.id, Review.created_at)
    ).all()
    turnaround = [_minutes(decided - created) for created, decided in first_decisions]

    item_ids = select(ContentVersion.content_item_id).join(Review, Review.content_version_id == ContentVersion.id).where(
        Review.id.in_(period_ids)
    )
    version_counts = db.execute(
        select(ContentVersion.content_item_id, func.count(ContentVersion.id))
        .where(ContentVersion.content_item_id.in_(item_ids))
        .group_by(ContentVersion.content_item_id)
    ).all()
    re_review_rate = (
        round(sum(1 for _, n in version_counts if n >= 2) / len(version_counts), 4) if version_counts else None
    )

    waiting_since = db.scalars(
        period.where(awaiting_decision_condition()).with_only_columns(Review.created_at)
    ).all()
    ages = [_minutes(now - created) for created in waiting_since]

    return BrandRiskOut(
        top_categories=[CategoryCount(category=c, count=n) for c, n in category_rows],
        median_turnaround_minutes=_median(turnaround),
        re_review_rate=re_review_rate,
        queue_age_minutes=QueueAge(median=_median(ages), oldest=round(max(ages), 1) if ages else None),
        sample_size=sample_size,
    )
