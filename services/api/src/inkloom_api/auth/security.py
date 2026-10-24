"""Password hashing and access tokens.

Email + password, bcrypt-hashed, a signed JWT bearer token. No refresh tokens, no magic links,
no OAuth — the simplest thing that fits a hackathon demo; revisit if the team needs SSO later.

A token is scoped to exactly one (user_id, organisation_id) pair, decided once at login
(`create_access_token`). It carries no role and no permissions: every request re-reads the
membership's current role and `is_active` flag from the database (`dependencies.py`), so a
revoked membership loses access immediately without needing a token denylist.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from ..config import MIN_AUTH_SECRET_CHARS, Settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False  # malformed hash; never a crash on login


class TokenError(Exception):
    """A token is missing, expired, malformed or incorrectly signed."""


def create_access_token(settings: Settings, user_id: uuid.UUID, organisation_id: uuid.UUID) -> str:
    if len(settings.auth_secret_key) < MIN_AUTH_SECRET_CHARS:
        raise RuntimeError(
            f"AUTH_SECRET_KEY is missing or shorter than {MIN_AUTH_SECRET_CHARS} characters"
        )
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(organisation_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.auth_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.auth_secret_key, algorithm=ALGORITHM)


def decode_access_token(settings: Settings, token: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns (user_id, organisation_id). Raises TokenError for any invalid token."""
    if len(settings.auth_secret_key) < MIN_AUTH_SECRET_CHARS:
        # Fail closed: with no (or a guessable) key no token can be trusted.
        raise TokenError("token verification is not configured")
    try:
        payload = jwt.decode(token, settings.auth_secret_key, algorithms=[ALGORITHM])
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["org"])
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise TokenError(str(exc)) from exc
