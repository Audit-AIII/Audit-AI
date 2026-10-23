"""Phase 5 task 6: idempotency keys on POST /api/reviews and rerun.

A client sends an `Idempotency-Key` header. The same key, same request, replays the first
response with no new job and no new LLM call. The same key with a *different* request body is
a client bug, not something to silently paper over - it gets a safe 409.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .models import IdempotencyKey


def hash_request_body(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def find_replay(
    db: Session, organisation_id: uuid.UUID, endpoint: str, key: str, request_hash: str
) -> dict | None:
    """Returns the stored response body to replay, or `None` if this key hasn't been used yet.
    Raises a safe 409 if the same key was used for a genuinely different request."""
    existing = (
        db.query(IdempotencyKey)
        .filter_by(organisation_id=organisation_id, endpoint=endpoint, key=key)
        .one_or_none()
    )
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Idempotency-Key was already used for a different request"
        )
    return existing.response_body


def record(
    db: Session,
    organisation_id: uuid.UUID,
    endpoint: str,
    key: str,
    request_hash: str,
    response_status: int,
    response_body: dict,
) -> None:
    db.add(
        IdempotencyKey(
            organisation_id=organisation_id,
            endpoint=endpoint,
            key=key,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
        )
    )
