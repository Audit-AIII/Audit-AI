"""The auth dependency every protected route takes a `Depends` on.

Loads the user and their membership fresh from the database on every request, and rejects a
revoked or inactive membership immediately (task 2). `organisation_id`, `user_id` and `role`
reach request handlers only through `AuthContext` — never read them from a request body or query
string (task 4); that is enforced by convention (no route parameter shares those names), not by
a runtime check, so review new routes for it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Membership, Organisation, User
from .permissions import Permission, role_has_permission
from .security import TokenError, decode_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user: User
    organisation: Organisation
    membership: Membership

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def organisation_id(self) -> uuid.UUID:
        return self.organisation.id

    @property
    def role(self) -> str:
        return self.membership.role

    def require(self, permission: Permission) -> None:
        if not role_has_permission(self.role, permission):
            # Safe 403: names the missing permission, never which other tenant/role could do it.
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"missing permission: {permission.value}"
            )


def get_current_membership(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    try:
        user_id, organisation_id = decode_access_token(settings, credentials.credentials)
    except TokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from None

    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user_id, Membership.organisation_id == organisation_id)
        .one_or_none()
    )
    if membership is None or not membership.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")

    user = db.get(User, user_id)
    organisation = db.get(Organisation, organisation_id)
    if user is None or organisation is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")

    return AuthContext(user=user, organisation=organisation, membership=membership)


def require_permission(permission: Permission):
    """`Depends(require_permission(Permission.MANAGE_SOURCES))` on any route that needs it."""

    def _check(auth: AuthContext = Depends(get_current_membership)) -> AuthContext:
        auth.require(permission)
        return auth

    return _check
