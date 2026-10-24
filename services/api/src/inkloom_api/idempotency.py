"""Phase 5 task 6: idempotency keys on POST /api/reviews and rerun.

A client sends an `Idempotency-Key` header. The same key, same request, replays the first
response with no new job and no new LLM call. The same key with a *different* request body is
a client bug, not something to silently paper over - it gets a safe 409.

The key is reserved (`claim`) inside the request's own transaction before any work, and its
response is filled in (`complete`) before that one commit. Two requests with the same key that
arrive together (a double click) therefore can't both run: the second one's insert waits on the
unique index until the first commits - then it replays the first response - or rolls back - then
it runs itself. If the first is still running when the second's statement timeout fires, the
second gets a 409 and can simply retry.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .models import IdempotencyKey

# idempotency_keys.key is String(200); a longer key used to fail the insert with a 500.
_KEY_PATTERN = re.compile(r"[\x21-\x7e]{1,200}")


def validated_key(key: str | None) -> str | None:
    """The header value, or a 422 if it isn't 1-200 visible ASCII characters."""
    if key is not None and not _KEY_PATTERN.fullmatch(key):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Idempotency-Key must be 1-200 visible ASCII characters",
        )
    return key


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


def claim(
    db: Session, organisation_id: uuid.UUID, endpoint: str, key: str, request_hash: str
) -> dict | None:
    """Reserves the key in the caller's transaction. Returns a stored response to replay instead
    if a request with this key already completed - including one that finished while this one
    waited for it."""
    replay = find_replay(db, organisation_id, endpoint, key, request_hash)
    if replay is not None:
        return replay
    try:
        with db.begin_nested():
            db.add(
                IdempotencyKey(
                    organisation_id=organisation_id,
                    endpoint=endpoint,
                    key=key,
                    request_hash=request_hash,
                )
            )
    except IntegrityError:
        # A concurrent request with the same key committed first while this insert waited.
        replay = find_replay(db, organisation_id, endpoint, key, request_hash)
        if replay is not None:
            return replay
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a request with this Idempotency-Key is still being processed"
        ) from None
    except OperationalError:
        # The statement timeout fired while waiting for a concurrent request with the same key.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a request with this Idempotency-Key is still being processed; retry shortly",
        ) from None
    return None


def complete(
    db: Session,
    organisation_id: uuid.UUID,
    endpoint: str,
    key: str,
    response_status: int,
    response_body: dict,
) -> None:
    """Stores the response on the key `claim` reserved; committed with the work itself."""
    row = (
        db.query(IdempotencyKey)
        .filter_by(organisation_id=organisation_id, endpoint=endpoint, key=key)
        .one()
    )
    row.response_status = response_status
    row.response_body = response_body
