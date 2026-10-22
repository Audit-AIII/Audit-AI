"""Login and session introspection. Not in 00_CONTEXT.md's route map (that table starts after
auth), but Member 1's frontend needs a real endpoint to replace its placeholder localStorage
session — see contract/README.md for the behaviour this gives them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..auth.dependencies import AuthContext, get_current_membership
from ..auth.security import create_access_token, verify_password
from ..config import Settings, get_settings
from ..db import get_db
from ..models import Membership, User
from ..schemas import LoginResponse, OrganisationOut, SessionInfo, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


_INVALID_CREDENTIALS = "invalid email or password"


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> LoginResponse:
    user = db.query(User).filter(User.email == body.email).one_or_none()
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
    )


@router.get("/me", response_model=SessionInfo)
def me(auth: AuthContext = Depends(get_current_membership)) -> SessionInfo:
    return SessionInfo(
        user=UserOut.model_validate(auth.user),
        organisation=OrganisationOut.model_validate(auth.organisation),
        role=auth.role,
    )
