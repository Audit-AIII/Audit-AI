"""POST /api/reviews, POST /api/reviews/upload, GET /api/reviews/{id}
(phase3_vertical_slice.md; upload added for self-serve onboarding, see
member3_backend/HANDOFF_self_serve_onboarding.md). POST /api/reviews/{id}/rerun
(phase6_versioning_approval_audit.md task 2). GET /api/reviews: the Review queue page's list.

Analysis runs synchronously (confirmed with the team): the request blocks until the engine
finishes, and the response already carries the final findings. No polling in this phase.

Phase 5 tasks 6-7: an `Idempotency-Key` header on either POST route replays the first response
with no second job and no second LLM call; `POST /api/reviews` (and `/upload`) is also
rate-limited per user and per organisation (rate_limit.py).
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from inkloom_verify.schemas import MAX_CONTENT_CHARS
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..config import Settings, get_settings
from ..db import get_db
from ..idempotency import find_replay, hash_request_body, record
from ..models import ContentItem, ContentVersion, EvidenceLink, Finding, Review
from ..rate_limit import rate_limited_submit_permission
from ..review_queries import reviews_in_organisation
from ..review_runner import start_review
from ..schemas import ReviewOut
from ..source_upload import extract_text, file_type_from_name, read_limited
from ..statuses import ReviewState
from ..tenancy import get_brand_profile_or_404, get_review_or_404

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

_CREATE_ENDPOINT = "POST /api/reviews"
_UPLOAD_ENDPOINT = "POST /api/reviews/upload"
_RERUN_ENDPOINT = "POST /api/reviews/{id}/rerun"


class ReviewCreateRequest(BaseModel):
    brand_id: uuid.UUID
    title: str | None = Field(default=None, max_length=300)
    text: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)


def _submit_content_and_review(
    db: Session,
    auth: AuthContext,
    *,
    endpoint: str,
    idempotency_key: str | None,
    request_hash: str | None,
    brand_id: uuid.UUID,
    title: str,
    text: str,
    audit_details_extra: dict | None = None,
) -> ReviewOut:
    """Shared by `POST /api/reviews` and `POST /api/reviews/upload`: replay check, tenant-checked
    brand, a new `ContentItem` + its first `ContentVersion`, run the review, audit
    `review.submitted`, commit, then (if an idempotency key was given) record the replay."""
    if idempotency_key:
        replay = find_replay(db, auth.organisation_id, endpoint, idempotency_key, request_hash)
        if replay is not None:
            return ReviewOut(**replay)

    # brand_id is checked against the authenticated organisation here — never trusted as-is.
    brand = get_brand_profile_or_404(db, auth.organisation_id, brand_id)

    content_item = ContentItem(
        organisation_id=auth.organisation_id,
        brand_profile_id=brand.id,
        title=title,
        created_by=auth.user_id,
    )
    db.add(content_item)
    db.flush()

    content_version = ContentVersion(
        content_item_id=content_item.id,
        version_number=1,
        text=text,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        created_by=auth.user_id,
    )
    db.add(content_version)
    db.flush()

    review = start_review(db, content_version, brand.id)
    details = {"content_item_id": str(content_item.id)}
    if audit_details_extra:
        details.update(audit_details_extra)
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="review.submitted",
        entity_type="review",
        entity_id=review.id,
        details=details,
        request_id=review.request_id,
    )

    db.commit()
    db.refresh(review)
    result = ReviewOut.from_model(review)
    if idempotency_key:
        # A second, small commit: accepted tradeoff - if the process died between these two
        # commits, a retried request would re-run once more rather than replay, which is safe
        # (never silently wrong), just not perfectly exactly-once under that specific crash.
        record(db, auth.organisation_id, endpoint, idempotency_key, request_hash, 201, result.model_dump(mode="json"))
        db.commit()
    return result


@router.post("", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def create_review(
    body: ReviewCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(rate_limited_submit_permission()),
    db: Session = Depends(get_db),
) -> ReviewOut:
    if not body.text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "text must not be blank")

    request_hash = hash_request_body(body.model_dump(mode="json")) if idempotency_key else None
    return _submit_content_and_review(
        db,
        auth,
        endpoint=_CREATE_ENDPOINT,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        brand_id=body.brand_id,
        title=body.title or body.text[:80],
        text=body.text,
    )


@router.post("/upload", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def create_review_from_upload(
    brand_id: uuid.UUID = Form(...),
    title: str | None = Form(default=None, max_length=300),
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(rate_limited_submit_permission()),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ReviewOut:
    """Self-serve onboarding's "check a draft" step: a pasted-text alternative for people who'd
    rather upload a file (.txt/.pdf/.docx, same as brand sources). The uploaded bytes are never
    stored - only the extracted text, as the content item's first version."""
    file_type = file_type_from_name(file.filename)
    content = read_limited(file, settings.max_source_upload_bytes)
    text = extract_text(file_type, content)
    if len(text) > MAX_CONTENT_CHARS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"extracted text exceeds the {MAX_CONTENT_CHARS:,} character limit"
        )

    resolved_title = (title or Path(file.filename or "").stem or "Untitled")[:300]
    file_sha256 = hashlib.sha256(content).hexdigest()
    request_hash = (
        hash_request_body({"brand_id": str(brand_id), "title": resolved_title, "file_sha256": file_sha256})
        if idempotency_key
        else None
    )
    return _submit_content_and_review(
        db,
        auth,
        endpoint=_UPLOAD_ENDPOINT,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        brand_id=brand_id,
        title=resolved_title,
        text=text,
        audit_details_extra={"source_file_type": file_type.value},
    )


@router.get("", response_model=list[ReviewOut])
def list_reviews(
    statuses: list[ReviewState] | None = Query(default=None, alias="status"),
    brand_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[ReviewOut]:
    """The caller's own reviews as a plain JSON array of full `ReviewOut` objects (findings and
    evidence included), newest first. `?status=` may repeat (any of them matches); `brand_id`
    narrows to one of the caller's brands - another account's brand is a 404, exactly like a
    brand that doesn't exist. Scope comes only from the authenticated membership."""
    if brand_id is not None:
        get_brand_profile_or_404(db, auth.organisation_id, brand_id)

    query = reviews_in_organisation(auth.organisation_id)
    if brand_id is not None:
        query = query.where(ContentItem.brand_profile_id == brand_id)
    if statuses:
        query = query.where(Review.status.in_([s.value for s in statuses]))
    query = (
        query.order_by(Review.created_at.desc(), Review.id.desc())
        .limit(limit)
        .offset(offset)
        # Everything ReviewOut.from_model touches, loaded in a fixed number of queries rather
        # than a few per review.
        .options(
            selectinload(Review.content_version).selectinload(ContentVersion.content_item).selectinload(ContentItem.brand_profile),
            selectinload(Review.findings).selectinload(Finding.evidence).selectinload(EvidenceLink.source),
            selectinload(Review.findings).selectinload(Finding.evidence).selectinload(EvidenceLink.source_version),
        )
    )
    return [ReviewOut.from_model(review) for review in db.scalars(query).all()]


@router.get("/{review_id}", response_model=ReviewOut)
def get_review(
    review_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ReviewOut:
    review = get_review_or_404(db, auth.organisation_id, review_id)
    return ReviewOut.from_model(review)


@router.post("/{review_id}/rerun", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def rerun_review(
    review_id: uuid.UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(require_permission(Permission.SUBMIT)),
    db: Session = Depends(get_db),
) -> ReviewOut:
    """Creates and runs a NEW review for the same content_version_id the given review used —
    the old review row is untouched (it stays whatever it was: failed, needs_human_review, ...).
    Useful after a provider failure, or after a brand source changed and the content should be
    re-checked without editing it."""
    # No request body to hash - the thing being deduplicated is "rerun THIS review", so the
    # target review_id itself is the hashed payload.
    request_hash = hash_request_body({"review_id": str(review_id)}) if idempotency_key else None
    if idempotency_key:
        replay = find_replay(db, auth.organisation_id, _RERUN_ENDPOINT, idempotency_key, request_hash)
        if replay is not None:
            return ReviewOut(**replay)

    old_review = get_review_or_404(db, auth.organisation_id, review_id)
    content_version = db.get(ContentVersion, old_review.content_version_id)
    content_item = db.get(ContentItem, content_version.content_item_id)

    new_review = start_review(db, content_version, content_item.brand_profile_id)
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="review.rerun",
        entity_type="review",
        entity_id=new_review.id,
        details={"rerun_of_review_id": str(old_review.id)},
        request_id=new_review.request_id,
    )

    db.commit()
    db.refresh(new_review)
    result = ReviewOut.from_model(new_review)
    if idempotency_key:
        record(db, auth.organisation_id, _RERUN_ENDPOINT, idempotency_key, request_hash, 201, result.model_dump(mode="json"))
        db.commit()
    return result
