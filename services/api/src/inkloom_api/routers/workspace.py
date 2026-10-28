"""Workspaces, members and invitations (Round 3 Phase 1, docs/governance.md section 7).

The workspace acted on is always the one in the caller's token (auth/dependencies.py), never an
id from the request: `/api/workspace/...` means "the workspace I'm signed into". The only routes
that name another workspace are switch-workspace (which checks the caller is an active member of
it, 404 otherwise) and accept (where the invitation itself names it).

Rules live in workspace_service.py.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ..auth.dependencies import AuthContext, get_current_membership
from ..auth.permissions import can_manage_members
from ..auth.security import create_access_token
from ..config import Settings, get_settings
from ..db import get_db
from ..models import Membership, Organisation, User
from ..schemas import (
    InvitationCreatedOut,
    InvitationOut,
    InvitationsOut,
    LoginResponse,
    MemberOut,
    MembersOut,
    OrganisationOut,
    UserOut,
    UserRefOut,
    WorkspaceMembershipOut,
    WorkspaceOut,
)
from ..statuses import MembershipRole
from ..tenancy import not_found
from ..workspace_service import (
    accept_invitation,
    active_members,
    change_member_role,
    create_invitation,
    invitation_status,
    list_invitations,
    remove_member,
    revoke_invitation,
)

router = APIRouter(tags=["workspace"])

_MANAGER_ACTIONS = ["invite", "change_role", "remove_member"]


def _session_for(
    settings: Settings, user: User, organisation: Organisation, role: str
) -> LoginResponse:
    return LoginResponse(
        access_token=create_access_token(settings, user.id, organisation.id),
        user=UserOut.model_validate(user),
        organisation=OrganisationOut.model_validate(organisation),
        role=role,
        expires_in=settings.auth_token_ttl_minutes * 60,
        workspace=WorkspaceOut.from_model(organisation),
    )


def _invitation_out(invitation) -> InvitationOut:
    return InvitationOut(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation_status(invitation).value,
        invited_by=UserRefOut.from_model(invitation.invited_by) if invitation.invited_by else None,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        revoked_at=invitation.revoked_at,
    )


# --- Workspaces --------------------------------------------------------------------------------


@router.get("/api/workspaces", response_model=list[WorkspaceMembershipOut])
def list_my_workspaces(
    auth: AuthContext = Depends(get_current_membership), db: Session = Depends(get_db)
) -> list[WorkspaceMembershipOut]:
    """Every workspace the caller is an active member of, oldest first (their personal one is
    always first)."""
    memberships = (
        db.query(Membership)
        .filter(Membership.user_id == auth.user_id, Membership.is_active.is_(True))
        .order_by(Membership.created_at.asc())
        .all()
    )
    return [
        WorkspaceMembershipOut(
            workspace=WorkspaceOut.from_model(m.organisation),
            role=m.role,
            is_current=m.organisation_id == auth.organisation_id,
        )
        for m in memberships
    ]


class SwitchWorkspaceRequest(BaseModel):
    workspace_id: uuid.UUID


@router.post("/api/auth/switch-workspace", response_model=LoginResponse)
def switch_workspace(
    body: SwitchWorkspaceRequest,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    """A new token for another workspace the caller belongs to. Not a member (or no such
    workspace): 404, the same either way."""
    membership = (
        db.query(Membership)
        .filter_by(user_id=auth.user_id, organisation_id=body.workspace_id, is_active=True)
        .one_or_none()
    )
    if membership is None:
        raise not_found("workspace not found")
    return _session_for(settings, auth.user, membership.organisation, membership.role)


# --- Members -----------------------------------------------------------------------------------


@router.get("/api/workspace/members", response_model=MembersOut)
def list_members(
    auth: AuthContext = Depends(get_current_membership), db: Session = Depends(get_db)
) -> MembersOut:
    return MembersOut(
        workspace=WorkspaceOut.from_model(auth.organisation),
        members=[
            MemberOut(
                user=UserRefOut.from_model(m.user),
                role=m.role,
                is_you=m.user_id == auth.user_id,
                joined_at=m.created_at,
            )
            for m in active_members(db, auth.organisation_id)
        ],
        allowed_actions=_MANAGER_ACTIONS if can_manage_members(auth.role) else [],
    )


class ChangeRoleRequest(BaseModel):
    role: str = Field(min_length=1, max_length=20)


@router.patch("/api/workspace/members/{user_id}", response_model=MemberOut)
def update_member_role(
    user_id: uuid.UUID,
    body: ChangeRoleRequest,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> MemberOut:
    membership = change_member_role(db, auth, user_id, body.role)
    db.commit()
    return MemberOut(
        user=UserRefOut.from_model(membership.user),
        role=membership.role,
        is_you=False,
        joined_at=membership.created_at,
    )


@router.delete("/api/workspace/members/{user_id}", response_model=MemberOut)
def delete_member(
    user_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> MemberOut:
    """Answers with the member as they were just before removal (their last role)."""
    membership = remove_member(db, auth, user_id)
    db.commit()
    return MemberOut(
        user=UserRefOut.from_model(membership.user),
        role=membership.role,
        is_you=membership.user_id == auth.user_id,
        joined_at=membership.created_at,
    )


# --- Invitations -------------------------------------------------------------------------------


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role: str = Field(default=MembershipRole.WRITER.value, min_length=1, max_length=20)


@router.post(
    "/api/workspace/invitations",
    response_model=InvitationCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
def invite(
    body: CreateInvitationRequest,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InvitationCreatedOut:
    """No email is sent (none is configured): the owner shares `accept_path` themselves. The
    token in it is never shown again."""
    invitation, token = create_invitation(db, auth, settings, body.email, body.role)
    db.commit()
    db.refresh(invitation)
    return InvitationCreatedOut(
        invitation=_invitation_out(invitation),
        token=token,
        accept_path=f"/invite/accept?token={quote(token)}",
    )


@router.get("/api/workspace/invitations", response_model=InvitationsOut)
def get_invitations(
    auth: AuthContext = Depends(get_current_membership), db: Session = Depends(get_db)
) -> InvitationsOut:
    return InvitationsOut(items=[_invitation_out(i) for i in list_invitations(db, auth)])


@router.post("/api/workspace/invitations/{invitation_id}/revoke", response_model=InvitationOut)
def revoke(
    invitation_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> InvitationOut:
    invitation = revoke_invitation(db, auth, invitation_id)
    db.commit()
    db.refresh(invitation)
    return _invitation_out(invitation)


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


@router.post("/api/invitations/accept", response_model=LoginResponse)
def accept(
    body: AcceptInvitationRequest,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    """Signed in as anyone (usually from their own personal workspace); answers with a session
    for the workspace the invitation names, in the role it names."""
    membership = accept_invitation(db, auth.user, body.token)
    db.commit()
    db.refresh(membership)
    return _session_for(settings, auth.user, membership.organisation, membership.role)
