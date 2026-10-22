"""POST /api/reviews, GET /api/reviews/{id} (phase3_vertical_slice.md).

Analysis runs synchronously (confirmed with the team): the request blocks until the engine
finishes, and the response already carries the final findings. No polling in this phase.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from inkloom_verify.schemas import CONTRACT_VERSION, MAX_CONTENT_CHARS
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..db import get_db
from ..engine.pipeline import build_corpus, run_review
from ..models import BrandSource, ContentItem, ContentVersion, Review, SourceVersion
from ..schemas import ReviewOut
from ..statuses import BrandSourceStatus, ReviewState
from ..tenancy import get_brand_profile_or_404, get_review_or_404

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class ReviewCreateRequest(BaseModel):
    brand_id: uuid.UUID
    title: str | None = Field(default=None, max_length=300)
    text: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)


def _latest_approved_sources(db: Session, brand_profile_id: uuid.UUID) -> list[tuple[BrandSource, SourceVersion]]:
    sources = (
        db.query(BrandSource)
        .filter(
            BrandSource.brand_profile_id == brand_profile_id,
            BrandSource.status == BrandSourceStatus.APPROVED.value,
        )
        .all()
    )
    entries: list[tuple[BrandSource, SourceVersion]] = []
    for source in sources:
        latest = (
            db.query(SourceVersion)
            .filter(SourceVersion.brand_source_id == source.id)
            .order_by(SourceVersion.version_number.desc())
            .first()
        )
        if latest is not None:
            entries.append((source, latest))
    return entries


@router.post("", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def create_review(
    body: ReviewCreateRequest,
    auth: AuthContext = Depends(require_permission(Permission.SUBMIT)),
    db: Session = Depends(get_db),
) -> ReviewOut:
    if not body.text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "text must not be blank")
    # brand_id is checked against the authenticated organisation here — never trusted as-is.
    brand = get_brand_profile_or_404(db, auth.organisation_id, body.brand_id)

    content_item = ContentItem(
        organisation_id=auth.organisation_id, title=body.title or body.text[:80], created_by=auth.user_id
    )
    db.add(content_item)
    db.flush()

    content_version = ContentVersion(
        content_item_id=content_item.id,
        version_number=1,
        text=body.text,
        text_sha256=hashlib.sha256(body.text.encode("utf-8")).hexdigest(),
        created_by=auth.user_id,
    )
    db.add(content_version)
    db.flush()

    review = Review(
        content_version_id=content_version.id,
        status=ReviewState.QUEUED.value,
        engine_contract_version=CONTRACT_VERSION,
        request_id=uuid.uuid4().hex,
    )
    db.add(review)
    db.flush()

    corpus = build_corpus(_latest_approved_sources(db, brand.id))
    run_review(db, review, content_version, corpus)

    db.commit()
    db.refresh(review)
    return ReviewOut.from_model(review)


@router.get("/{review_id}", response_model=ReviewOut)
def get_review(
    review_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ReviewOut:
    review = get_review_or_404(db, auth.organisation_id, review_id)
    return ReviewOut.from_model(review)
