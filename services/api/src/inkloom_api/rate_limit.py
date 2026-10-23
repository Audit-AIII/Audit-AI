"""Phase 5 task 7: rate limits per user and per organisation on review submissions.

In-memory, fixed-window, single-process. Documented limitation: a multi-worker deployment would
need a shared store (Redis, the database) since each worker would otherwise track its own
counters - out of scope for this hackathon's single-process deployment, and noted in the README.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from threading import Lock

from fastapi import Depends, HTTPException, Request, status

from .auth.dependencies import AuthContext, require_permission
from .auth.permissions import Permission
from .config import Settings, get_settings

_lock = Lock()
_user_hits: dict[str, list[float]] = defaultdict(list)
_org_hits: dict[str, list[float]] = defaultdict(list)
_ip_hits: dict[str, list[float]] = defaultdict(list)


def _retry_after(hits: list[float], window_seconds: float, now: float) -> int:
    """Whole seconds until the oldest counted hit leaves the window (at least 1)."""
    return max(1, math.ceil(hits[0] + window_seconds - now)) if hits else 1


def _too_many(message: str, hits: list[float], window_seconds: float, now: float) -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message,
                         headers={"Retry-After": str(_retry_after(hits, window_seconds, now))})


def _prune_and_count(hits: list[float], window_seconds: float, now: float) -> int:
    cutoff = now - window_seconds
    while hits and hits[0] < cutoff:
        hits.pop(0)
    return len(hits)


def reset_rate_limits() -> None:
    """Test-only: clears all counters so tests don't interfere with each other."""
    with _lock:
        _user_hits.clear()
        _org_hits.clear()
        _ip_hits.clear()


def enforce_submission_rate_limit(auth: AuthContext, settings: Settings) -> None:
    now = time.monotonic()
    user_key, org_key = str(auth.user_id), str(auth.organisation_id)
    with _lock:
        if _prune_and_count(_user_hits[user_key], settings.rate_limit_window_seconds, now) >= settings.rate_limit_submissions_per_user:
            raise _too_many("too many submissions from this user; slow down", _user_hits[user_key],
                            settings.rate_limit_window_seconds, now)
        if (
            _prune_and_count(_org_hits[org_key], settings.rate_limit_window_seconds, now)
            >= settings.rate_limit_submissions_per_organisation
        ):
            raise _too_many("this organisation has submitted too many reviews recently", _org_hits[org_key],
                            settings.rate_limit_window_seconds, now)
        _user_hits[user_key].append(now)
        _org_hits[org_key].append(now)


def enforce_registration_rate_limit(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """`Depends(enforce_registration_rate_limit)` on `POST /api/auth/register`. Unauthenticated -
    there is no user or organisation yet - so this keys on the caller's IP alone, read only from
    `request.client.host` (never the `X-Forwarded-For` header, which an untrusted caller can set
    to anything and use to reset their own budget)."""
    now = time.monotonic()
    ip_key = request.client.host if request.client else "unknown"
    with _lock:
        if (
            _prune_and_count(_ip_hits[ip_key], settings.rate_limit_registration_window_seconds, now)
            >= settings.rate_limit_registrations_per_ip
        ):
            raise _too_many("too many registration attempts from this address; slow down", _ip_hits[ip_key],
                            settings.rate_limit_registration_window_seconds, now)
        _ip_hits[ip_key].append(now)


def rate_limited_submit_permission():
    """`Depends(rate_limited_submit_permission())` - the `submit` permission check, plus the
    rate limit, in one dependency. Permission is checked first: an unauthorized caller
    shouldn't consume rate-limit budget."""

    def _check(
        auth: AuthContext = Depends(require_permission(Permission.SUBMIT)),
        settings: Settings = Depends(get_settings),
    ) -> AuthContext:
        enforce_submission_rate_limit(auth, settings)
        return auth

    return _check
