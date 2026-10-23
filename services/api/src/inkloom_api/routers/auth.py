"""Login, self-serve registration, and session introspection. Not in 00_CONTEXT.md's route map
(that table starts after auth), but Member 1's frontend needs a real endpoint to replace its
placeholder localStorage session — see contract/README.md for the behaviour this gives them.

Registration (member3_backend/HANDOFF_self_serve_onboarding.md) is the self-serve onboarding
entry point: a visitor signs up with any email and gets a private account (an organisation only
they belong to), an `admin` membership - which now just means "account owner" - and a starter
brand, all in one transaction, with no brand id or invite needed.
"""

from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership
from ..auth.security import create_access_token, hash_password, verify_password
from ..config import Settings, get_settings
from ..db import get_db
from ..models import BrandProfile, Membership, Organisation, User
from ..rate_limit import enforce_registration_rate_limit
from ..schemas import BrandOut, LoginResponse, OrganisationOut, RegisterResponse, SessionInfo, UserOut
from ..statuses import MembershipRole

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


_INVALID_CREDENTIALS = "invalid email or password"
_DUPLICATE_EMAIL = "an account with this email already exists; sign in instead"


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> LoginResponse:
    # Case-insensitive: register() always stores email lower-cased, but older rows (e.g. the
    # seed script, written before this lookup changed) may not be, so compare both sides folded.
    user = db.query(User).filter(func.lower(User.email) == body.email.lower()).one_or_none()
    if user is None or user.password_hash is None or not verify_password(body.password, user.password_hash):
        # Same message whether the email is unknown or the password is wrong: don't let a caller
        # enumerate registered addresses.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)

    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.is_active.is_(True))
        .order_by(Membership.created_at.asc())
        .first()
    )
    if membership is None:
        # No active organisation to sign into. Same generic message as a wrong password, for the
        # same reason.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)

    token = create_access_token(settings, user.id, membership.organisation_id)
    return LoginResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        organisation=OrganisationOut.model_validate(membership.organisation),
        role=membership.role,
        expires_in=settings.auth_token_ttl_minutes * 60,
    )


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = Field(default=None, max_length=200)
    organisation_name: str | None = Field(default=None, max_length=200)
    brand_name: str | None = Field(default=None, max_length=200)

    @field_validator("display_name", "organisation_name", "brand_name", mode="before")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("password must be at least 8 characters")
        if len(value.encode("utf-8")) > 72:
            # bcrypt (auth/security.py's hash_password) only looks at the first 72 bytes - reject
            # up front rather than silently hashing a truncated password.
            raise ValueError("password must be at most 72 bytes long")
        return value


_SLUG_INVALID = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    base = _SLUG_INVALID.sub("-", name.strip().lower()).strip("-")
    # 8 random hex chars make the slug unique even when two organisations pick the same name -
    # the alternative (retry-on-conflict) adds a loop for a case that barely matters.
    return f"{(base or 'org')[:40]}-{secrets.token_hex(4)}"


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _rate_limit: None = Depends(enforce_registration_rate_limit),
) -> RegisterResponse:
    normalized_email = body.email.lower()
    if db.query(User).filter(func.lower(User.email) == normalized_email).one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, _DUPLICATE_EMAIL)

    local_part = normalized_email.split("@", 1)[0]
    organisation_name = (body.organisation_name or f"{body.display_name or local_part}'s workspace")[:200]
    brand_name = body.brand_name or "My brand"

    user = User(email=normalized_email, display_name=body.display_name, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # The race this is for: two concurrent registrations with the same email both pass the
        # query above, then both try to flush - only one wins the unique constraint.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, _DUPLICATE_EMAIL) from None

    org = Organisation(name=organisation_name, slug=_slugify(organisation_name))
    db.add(org)
    db.flush()

    # role is always "admin" here - never taken from the request body (RegisterRequest has no
    # role/organisation_id field at all, so even an extra field in the body is silently ignored).
    # Individual-user mode: "admin" simply means "account owner" - this organisation is this one
    # person's private account, and roles no longer gate anything (auth/permissions.py).
    db.add(Membership(organisation_id=org.id, user_id=user.id, role=MembershipRole.ADMIN.value, is_active=True))

    brand = BrandProfile(organisation_id=org.id, name=brand_name)
    db.add(brand)
    db.flush()

    log_audit_event(
        db,
        organisation_id=org.id,
        actor_user_id=user.id,
        event_type="account.registered",
        entity_type="organisation",
        entity_id=org.id,
        details={"brand_id": str(brand.id)},  # never email/name here (audit.py's own rule)
    )

    db.commit()
    db.refresh(user)
    db.refresh(org)
    db.refresh(brand)

    token = create_access_token(settings, user.id, org.id)
    return RegisterResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        organisation=OrganisationOut.model_validate(org),
        role=MembershipRole.ADMIN.value,
        expires_in=settings.auth_token_ttl_minutes * 60,
        brand=BrandOut(
            id=brand.id,
            name=brand.name,
            description=brand.description,
            approved_source_count=0,
            created_at=brand.created_at,
        ),
    )


@router.get("/me", response_model=SessionInfo)
def me(auth: AuthContext = Depends(get_current_membership)) -> SessionInfo:
    return SessionInfo(
        user=UserOut.model_validate(auth.user),
        organisation=OrganisationOut.model_validate(auth.organisation),
        role=auth.role,
    )
