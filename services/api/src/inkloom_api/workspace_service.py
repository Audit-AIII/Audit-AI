"""Workspace membership and invitations (Round 3 Phase 1, docs/governance.md).

The router (routers/workspace.py) stays thin; every rule lives here:

- only owners manage members (auth/permissions.py `can_manage_members`), and nobody grants a
  role they don't hold (`can_grant_role`);
- nobody changes their own role, and a workspace always keeps at least one active owner. The
  owner rows are locked (`FOR UPDATE`) before counting, so two concurrent demotions can't both
  pass the check;
- an invitation token is `secrets.token_urlsafe(32)`, stored only as its sha256, single use, and
  bound to its workspace, email and role. Accepting grants exactly that role in exactly that
  workspace: the request carries nothing else.

Every change writes its audit event in the caller's transaction (audit.py). Details never hold an
email or a token.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import log_audit_event
from .auth.dependencies import AuthContext
from .auth.permissions import can_grant_role, can_manage_members, is_owner
from .config import Settings
from .errors import ApiException, ErrorCode
from .models import Invitation, Membership, User
from .statuses import InvitationStatus, MembershipRole, values
from .tenancy import not_found


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invitation_status(invitation: Invitation, now: datetime | None = None) -> InvitationStatus:
    if invitation.accepted_at is not None:
        return InvitationStatus.ACCEPTED
    if invitation.revoked_at is not None:
        return InvitationStatus.REVOKED
    if invitation.expires_at <= (now or datetime.now(UTC)):
        return InvitationStatus.EXPIRED
    return InvitationStatus.PENDING


def _check_grant(auth: AuthContext, role: str) -> None:
    """422 for a name that isn't a role at all; 403 for a real role the caller can't grant
    (including the legacy names, which are never granted any more)."""
    if role not in values(MembershipRole):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown role: {role[:20]}")
    if not can_grant_role(auth.role, role):
        raise ApiException(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.ROLE_ESCALATION_FORBIDDEN,
            "you cannot give a role you do not hold",
        )


def require_member_manager(auth: AuthContext) -> None:
    if not can_manage_members(auth.role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "only a workspace owner can manage members and invitations"
        )


def active_members(db: Session, organisation_id: uuid.UUID) -> list[Membership]:
    return (
        db.query(Membership)
        .filter(Membership.organisation_id == organisation_id, Membership.is_active.is_(True))
        .order_by(Membership.created_at.asc())
        .all()
    )


def _active_member_or_404(
    db: Session, organisation_id: uuid.UUID, user_id: uuid.UUID
) -> Membership:
    membership = (
        db.query(Membership)
        .filter_by(organisation_id=organisation_id, user_id=user_id, is_active=True)
        .with_for_update()
        .one_or_none()
    )
    if membership is None:
        raise not_found("member not found")
    return membership


def _ensure_another_owner(db: Session, organisation_id: uuid.UUID, leaving: Membership) -> None:
    """Raises unless an active owner other than `leaving` stays in the workspace."""
    owners = [
        m
        for m in db.query(Membership)
        .filter(Membership.organisation_id == organisation_id, Membership.is_active.is_(True))
        .with_for_update()
        .all()
        if is_owner(m.role)
    ]
    if not any(m.id != leaving.id for m in owners):
        raise ApiException(
            status.HTTP_409_CONFLICT,
            ErrorCode.LAST_OWNER_REQUIRED,
            "a workspace must keep at least one owner",
        )


# --- Invitations ------------------------------------------------------------------------------


def create_invitation(
    db: Session, auth: AuthContext, settings: Settings, email: str, role: str
) -> tuple[Invitation, str]:
    """Returns the new invitation and its raw token (the only time the token exists)."""
    require_member_manager(auth)
    _check_grant(auth, role)
    email = email.strip().lower()

    already_member = (
        db.query(Membership)
        .join(User, User.id == Membership.user_id)
        .filter(
            Membership.organisation_id == auth.organisation_id,
            Membership.is_active.is_(True),
            func.lower(User.email) == email,
        )
        .first()
    )
    if already_member is not None:
        raise ApiException(
            status.HTTP_409_CONFLICT,
            ErrorCode.ALREADY_MEMBER,
            "this person is already a member of the workspace",
        )

    now = datetime.now(UTC)
    open_invitation = (
        db.query(Invitation)
        .filter(
            Invitation.organisation_id == auth.organisation_id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .with_for_update()
        .one_or_none()
    )
    if open_invitation is not None:
        if invitation_status(open_invitation, now) is InvitationStatus.PENDING:
            raise ApiException(
                status.HTTP_409_CONFLICT,
                ErrorCode.INVITE_ALREADY_PENDING,
                "an invitation for this email is already pending",
            )
        # Expired but still open: close it so the one-open-invitation index lets a new one in.
        open_invitation.revoked_at = now
        open_invitation.revoked_by_user_id = auth.user_id
        db.flush()

    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        organisation_id=auth.organisation_id,
        email=email,
        role=role,
        token_hash=hash_token(token),
        invited_by_user_id=auth.user_id,
        created_at=now,
        expires_at=now + timedelta(days=settings.invitation_ttl_days),
    )
    db.add(invitation)
    try:
        db.flush()
    except IntegrityError:
        # A concurrent request created the same open invitation first.
        db.rollback()
        raise ApiException(
            status.HTTP_409_CONFLICT,
            ErrorCode.INVITE_ALREADY_PENDING,
            "an invitation for this email is already pending",
        ) from None

    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="invite_created",
        entity_type="invitation",
        entity_id=invitation.id,
        details={"role": role, "expires_at": invitation.expires_at.isoformat()},
    )
    return invitation, token


def list_invitations(db: Session, auth: AuthContext) -> list[Invitation]:
    require_member_manager(auth)
    return (
        db.query(Invitation)
        .filter_by(organisation_id=auth.organisation_id)
        .order_by(Invitation.created_at.desc(), Invitation.id.desc())
        .all()
    )


def revoke_invitation(db: Session, auth: AuthContext, invitation_id: uuid.UUID) -> Invitation:
    require_member_manager(auth)
    invitation = db.get(Invitation, invitation_id, with_for_update=True)
    if invitation is None or invitation.organisation_id != auth.organisation_id:
        raise not_found("invitation not found")
    state = invitation_status(invitation)
    if state is InvitationStatus.ACCEPTED:
        raise ApiException(
            status.HTTP_409_CONFLICT,
            ErrorCode.INVITE_ALREADY_USED,
            "this invitation has already been accepted",
        )
    if state is InvitationStatus.REVOKED:
        raise ApiException(
            status.HTTP_409_CONFLICT, ErrorCode.INVITE_REVOKED, "this invitation was withdrawn"
        )
    invitation.revoked_at = datetime.now(UTC)
    invitation.revoked_by_user_id = auth.user_id
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="invite_revoked",
        entity_type="invitation",
        entity_id=invitation.id,
        details={"role": invitation.role, "was": state.value},
    )
    return invitation


def accept_invitation(db: Session, user: User, token: str) -> Membership:
    """`user` is whoever is signed in. The workspace and role come only from the invitation."""
    invitation = (
        db.query(Invitation).filter_by(token_hash=hash_token(token)).with_for_update().one_or_none()
    )
    if invitation is None:
        raise not_found("invitation not found")
    state = invitation_status(invitation)
    if state is InvitationStatus.ACCEPTED:
        raise ApiException(
            status.HTTP_409_CONFLICT,
            ErrorCode.INVITE_ALREADY_USED,
            "this invitation has already been accepted",
        )
    if state is InvitationStatus.REVOKED:
        raise ApiException(
            status.HTTP_409_CONFLICT, ErrorCode.INVITE_REVOKED, "this invitation was withdrawn"
        )
    if state is InvitationStatus.EXPIRED:
        raise ApiException(
            status.HTTP_409_CONFLICT,
            ErrorCode.INVITE_EXPIRED,
            "this invitation has expired; ask for a new one",
        )
    if user.email.lower() != invitation.email:
        raise ApiException(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INVITE_EMAIL_MISMATCH,
            "this invitation was sent to a different email address",
        )

    membership = (
        db.query(Membership)
        .filter_by(organisation_id=invitation.organisation_id, user_id=user.id)
        .with_for_update()
        .one_or_none()
    )
    if membership is not None and membership.is_active:
        raise ApiException(
            status.HTTP_409_CONFLICT,
            ErrorCode.ALREADY_MEMBER,
            "you are already a member of this workspace",
        )
    if membership is None:
        membership = Membership(
            organisation_id=invitation.organisation_id,
            user_id=user.id,
            role=invitation.role,
            is_active=True,
        )
        db.add(membership)
    else:  # a former member, removed earlier: back in, with the invited role only
        membership.role = invitation.role
        membership.is_active = True
    invitation.accepted_at = datetime.now(UTC)
    invitation.accepted_by_user_id = user.id
    db.flush()

    log_audit_event(
        db,
        organisation_id=invitation.organisation_id,
        actor_user_id=user.id,
        event_type="invite_accepted",
        entity_type="invitation",
        entity_id=invitation.id,
        details={"role": invitation.role, "membership_id": str(membership.id)},
    )
    return membership


# --- Members ----------------------------------------------------------------------------------


def change_member_role(db: Session, auth: AuthContext, user_id: uuid.UUID, role: str) -> Membership:
    require_member_manager(auth)
    if user_id == auth.user_id:
        raise ApiException(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.SELF_ROLE_CHANGE_FORBIDDEN,
            "you cannot change your own role",
        )
    _check_grant(auth, role)
    membership = _active_member_or_404(db, auth.organisation_id, user_id)
    before = membership.role
    if is_owner(before) and not is_owner(role):
        _ensure_another_owner(db, auth.organisation_id, membership)
    membership.role = role
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="member_role_changed",
        entity_type="membership",
        entity_id=membership.id,
        details={"user_id": str(user_id), "before": {"role": before}, "after": {"role": role}},
    )
    return membership


def remove_member(db: Session, auth: AuthContext, user_id: uuid.UUID) -> Membership:
    """Deactivates the membership (kept for the audit trail and for a later re-invite). The
    removed person's tokens for this workspace stop working on their next request
    (auth/dependencies.py reloads the membership every time)."""
    require_member_manager(auth)
    membership = _active_member_or_404(db, auth.organisation_id, user_id)
    if is_owner(membership.role):
        _ensure_another_owner(db, auth.organisation_id, membership)
    membership.is_active = False
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="member_removed",
        entity_type="membership",
        entity_id=membership.id,
        details={"user_id": str(user_id), "before": {"role": membership.role}},
    )
    return membership
