"""Starts a review for an existing, already-persisted `ContentVersion`. Shared by
`POST /api/reviews` (Phase 3), `POST /api/content/{id}/versions` and `POST /api/reviews/{id}/rerun`
(Phase 6) — all three do the same thing from this point on: look up the brand's approved
sources, build the corpus, run the pipeline, synchronously, against one content version.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from inkloom_verify.providers.base import LLMProvider
from inkloom_verify.schemas import CONTRACT_VERSION
from sqlalchemy.orm import Session

from .engine.pipeline import build_corpus, run_review
from .models import BrandSource, ContentVersion, Review, SourceVersion
from .statuses import BrandSourceSensitivity, BrandSourceStatus, ReviewState


def latest_approved_sources(db: Session, brand_profile_id: uuid.UUID) -> list[tuple[BrandSource, SourceVersion]]:
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


def start_review(
    db: Session,
    content_version: ContentVersion,
    brand_profile_id: uuid.UUID | None,
    provider_builders: list[tuple[str, Callable[[], LLMProvider]]] | None = None,
) -> Review:
    """Creates and runs a new `Review` row. Caller commits. `brand_profile_id` may be `None`
    for a content item created before Phase 6 (no brand recorded) - treated the same as a brand
    with zero approved sources: the review fails cleanly rather than crashing.
    `provider_builders`: see `engine.pipeline.run_review` (seed script only)."""
    review = Review(
        content_version_id=content_version.id,
        status=ReviewState.QUEUED.value,
        engine_contract_version=CONTRACT_VERSION,
        request_id=uuid.uuid4().hex,
    )
    db.add(review)
    db.flush()

    entries = latest_approved_sources(db, brand_profile_id) if brand_profile_id else []
    corpus = build_corpus(entries)
    # Phase 5 task 8: if ANY source in scope is confidential, the whole review is treated as
    # confidential - a mixed-sensitivity corpus must not let the content touch a cloud provider
    # just because some of its other sources are normal.
    confidential = any(source.sensitivity == BrandSourceSensitivity.CONFIDENTIAL.value for source, _ in entries)
    run_review(db, review, content_version, corpus, confidential=confidential, provider_builders=provider_builders)
    return review
