"""Round 3 Phase 1: personal workspaces, members and invitations (docs/governance.md).

Every test goes through the real HTTP routes with separately registered users, so each one also
proves the personal-workspace default still holds for everybody involved.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from conftest import join_workspace as _join
from conftest import requires_db
from inkloom_api.models import AuditEvent, Invitation, Membership

pytestmark = requires_db


def _invite(client, owner, email: str, role: str = "writer"):
    return client.post(
        "/api/workspace/invitations", json={"email": email, "role": role}, headers=owner.headers
    )


def _email(account, client) -> str:
    return client.get("/api/auth/me", headers=account.headers).json()["user"]["email"]


def _code(response) -> str:
    return response.json()["error"]["code"]


def _events(db_session, organisation_id: str, event_type: str) -> list[AuditEvent]:
    db_session.expire_all()
    return (
        db_session.query(AuditEvent)
        .filter_by(organisation_id=uuid.UUID(organisation_id), event_type=event_type)
        .all()
    )


# --- Personal workspace default ----------------------------------------------------------------


def test_registration_creates_a_personal_workspace_owned_by_the_user(
    client, account_factory
) -> None:
    owner = account_factory("solo", with_source=False)
    assert owner.role == "owner"

    me = client.get("/api/auth/me", headers=owner.headers).json()
    assert me["workspace"] == {
        "id": owner.organisation_id,
        "name": me["organisation"]["name"],
        "is_personal": True,
    }
    workspaces = client.get("/api/workspaces", headers=owner.headers).json()
    assert [(w["workspace"]["id"], w["role"], w["is_current"]) for w in workspaces] == [
        (owner.organisation_id, "owner", True)
    ]
    members = client.get("/api/workspace/members", headers=owner.headers).json()
    assert [(m["role"], m["is_you"]) for m in members["members"]] == [("owner", True)]
    assert members["allowed_actions"] == ["invite", "change_role", "remove_member"]


# --- Invitation lifecycle ----------------------------------------------------------------------


def test_invite_and_accept_grants_exactly_the_invited_role_in_that_workspace(
    client, account_factory, db_session
) -> None:
    owner = account_factory("owner", with_source=False)
    member = account_factory("member", with_source=False)
    personal_workspace = member.organisation_id

    created = _invite(client, owner, _email(member, client), "reviewer")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["invitation"]["status"] == "pending"
    assert body["invitation"]["role"] == "reviewer"
    assert body["accept_path"].endswith(body["token"])
    expires = datetime.fromisoformat(body["invitation"]["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= timedelta(days=7)

    # Only the hash is stored.
    stored = db_session.get(Invitation, uuid.UUID(body["invitation"]["id"]))
    assert stored.token_hash == hashlib.sha256(body["token"].encode()).hexdigest()
    assert body["token"] not in stored.token_hash

    # Extra fields can't change the workspace or role.
    accepted = client.post(
        "/api/invitations/accept",
        json={"token": body["token"], "role": "owner", "workspace_id": personal_workspace},
        headers=member.headers,
    )
    assert accepted.status_code == 200, accepted.text
    session = accepted.json()
    assert session["role"] == "reviewer"
    assert session["organisation"]["id"] == owner.organisation_id
    assert session["workspace"]["is_personal"] is True  # the owner's personal workspace

    member.token = session["access_token"]
    me = client.get("/api/auth/me", headers=member.headers).json()
    assert (me["organisation"]["id"], me["role"]) == (owner.organisation_id, "reviewer")

    workspaces = client.get("/api/workspaces", headers=member.headers).json()
    assert [(w["workspace"]["id"], w["role"], w["is_current"]) for w in workspaces] == [
        (personal_workspace, "owner", False),
        (owner.organisation_id, "reviewer", True),
    ]
    roster = client.get("/api/workspace/members", headers=owner.headers).json()["members"]
    assert sorted(m["role"] for m in roster) == ["owner", "reviewer"]
    assert all("email" not in m["user"] for m in roster)

    # Switching back to the personal workspace still works, with its own role.
    switched = client.post(
        "/api/auth/switch-workspace",
        json={"workspace_id": personal_workspace},
        headers=member.headers,
    )
    assert switched.status_code == 200, switched.text
    assert (switched.json()["role"], switched.json()["workspace"]["id"]) == (
        "owner",
        personal_workspace,
    )

    assert len(_events(db_session, owner.organisation_id, "invite_created")) == 1
    accepted_events = _events(db_session, owner.organisation_id, "invite_accepted")
    assert [str(e.actor_user_id) for e in accepted_events] == [member.user_id]
    assert accepted_events[0].details["role"] == "reviewer"


def test_listing_invitations_shows_each_status(client, account_factory, db_session) -> None:
    owner = account_factory("owner", with_source=False)
    member = account_factory("member", with_source=False)
    _join(client, owner, member, "writer")
    revoked = _invite(client, owner, "revoked@example.com").json()["invitation"]["id"]
    client.post(f"/api/workspace/invitations/{revoked}/revoke", headers=owner.headers)
    _invite(client, owner, "pending@example.com")

    items = client.get("/api/workspace/invitations", headers=owner.headers).json()["items"]
    assert sorted(i["status"] for i in items) == ["accepted", "pending", "revoked"]
    assert all(i["invited_by"]["id"] == owner.user_id for i in items)
    assert all("token" not in i and "token_hash" not in i for i in items)


def test_duplicate_pending_invitation_is_refused(client, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    assert _invite(client, owner, "dup@example.com").status_code == 201
    again = _invite(client, owner, "DUP@example.com", "reviewer")  # case-insensitive
    assert again.status_code == 409
    assert _code(again) == "INVITE_ALREADY_PENDING"


def test_unknown_token_is_not_found(client, account_factory) -> None:
    member = account_factory("member", with_source=False)
    response = client.post(
        "/api/invitations/accept", json={"token": "not-a-real-token"}, headers=member.headers
    )
    assert response.status_code == 404
    assert _code(response) == "NOT_FOUND"


def test_expired_invitation_cannot_be_accepted_and_can_be_reissued(
    client, account_factory, db_session
) -> None:
    owner = account_factory("owner", with_source=False)
    member = account_factory("member", with_source=False)
    email = _email(member, client)
    created = _invite(client, owner, email).json()

    invitation = db_session.get(Invitation, uuid.UUID(created["invitation"]["id"]))
    invitation.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    response = client.post(
        "/api/invitations/accept", json={"token": created["token"]}, headers=member.headers
    )
    assert response.status_code == 409
    assert _code(response) == "INVITE_EXPIRED"
    assert (
        db_session.query(Membership)
        .filter_by(
            organisation_id=uuid.UUID(owner.organisation_id), user_id=uuid.UUID(member.user_id)
        )
        .count()
        == 0
    )

    # An expired invitation doesn't block a new one for the same email.
    assert _invite(client, owner, email).status_code == 201


def test_revoked_invitation_cannot_be_accepted(client, account_factory, db_session) -> None:
    owner = account_factory("owner", with_source=False)
    member = account_factory("member", with_source=False)
    created = _invite(client, owner, _email(member, client)).json()

    revoked = client.post(
        f"/api/workspace/invitations/{created['invitation']['id']}/revoke", headers=owner.headers
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"
    again = client.post(
        f"/api/workspace/invitations/{created['invitation']['id']}/revoke", headers=owner.headers
    )
    assert again.status_code == 409 and _code(again) == "INVITE_REVOKED"

    response = client.post(
        "/api/invitations/accept", json={"token": created["token"]}, headers=member.headers
    )
    assert response.status_code == 409
    assert _code(response) == "INVITE_REVOKED"
    assert len(_events(db_session, owner.organisation_id, "invite_revoked")) == 1


def test_invitation_is_single_use(client, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    member = account_factory("member", with_source=False)
    created = _invite(client, owner, _email(member, client)).json()
    first = client.post(
        "/api/invitations/accept", json={"token": created["token"]}, headers=member.headers
    )
    assert first.status_code == 200, first.text

    member.token = first.json()["access_token"]
    second = client.post(
        "/api/invitations/accept", json={"token": created["token"]}, headers=member.headers
    )
    assert second.status_code == 409
    assert _code(second) == "INVITE_ALREADY_USED"

    revoke = client.post(
        f"/api/workspace/invitations/{created['invitation']['id']}/revoke", headers=owner.headers
    )
    assert revoke.status_code == 409 and _code(revoke) == "INVITE_ALREADY_USED"


def test_invitation_for_another_email_is_refused(client, account_factory, db_session) -> None:
    owner = account_factory("owner", with_source=False)
    intended = account_factory("intended", with_source=False)
    stranger = account_factory("stranger", with_source=False)
    created = _invite(client, owner, _email(intended, client)).json()

    response = client.post(
        "/api/invitations/accept", json={"token": created["token"]}, headers=stranger.headers
    )
    assert response.status_code == 403
    assert _code(response) == "INVITE_EMAIL_MISMATCH"
    assert (
        db_session.query(Membership)
        .filter_by(
            organisation_id=uuid.UUID(owner.organisation_id), user_id=uuid.UUID(stranger.user_id)
        )
        .count()
        == 0
    )
    # Still usable by the right person.
    ok = client.post(
        "/api/invitations/accept", json={"token": created["token"]}, headers=intended.headers
    )
    assert ok.status_code == 200, ok.text


def test_existing_member_cannot_be_invited_again(client, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    member = account_factory("member", with_source=False)
    _join(client, owner, member, "writer")
    again = _invite(client, owner, _email(member, client), "approver")
    assert again.status_code == 409
    assert _code(again) == "ALREADY_MEMBER"
    self_invite = _invite(client, owner, _email(owner, client), "writer")
    assert self_invite.status_code == 409 and _code(self_invite) == "ALREADY_MEMBER"


# --- Privilege escalation ----------------------------------------------------------------------


def test_only_owners_manage_members_and_invitations(client, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    approver = account_factory("approver", with_source=False)
    writer = account_factory("writer", with_source=False)
    _join(client, owner, approver, "approver")
    _join(client, owner, writer, "writer")
    pending = _invite(client, owner, "someone@example.com").json()["invitation"]["id"]

    for member in (approver, writer):
        for response in (
            _invite(client, member, "x@example.com", "writer"),
            _invite(client, member, "y@example.com", "owner"),
            client.get("/api/workspace/invitations", headers=member.headers),
            client.post(f"/api/workspace/invitations/{pending}/revoke", headers=member.headers),
            client.patch(
                f"/api/workspace/members/{owner.user_id}",
                json={"role": "writer"},
                headers=member.headers,
            ),
            client.delete(f"/api/workspace/members/{owner.user_id}", headers=member.headers),
        ):
            assert response.status_code == 403, response.text
            assert _code(response) == "FORBIDDEN"
        listing = client.get("/api/workspace/members", headers=member.headers).json()
        assert listing["allowed_actions"] == []

    roster = client.get("/api/workspace/members", headers=owner.headers).json()["members"]
    assert sorted(m["role"] for m in roster) == ["approver", "owner", "writer"]


def test_roles_outside_the_four_team_roles_cannot_be_granted(client, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    member = account_factory("member", with_source=False)
    _join(client, owner, member, "writer")

    legacy = _invite(client, owner, "legacy@example.com", "admin")
    assert legacy.status_code == 403 and _code(legacy) == "ROLE_ESCALATION_FORBIDDEN"
    unknown = _invite(client, owner, "unknown@example.com", "superuser")
    assert unknown.status_code == 422 and _code(unknown) == "VALIDATION_ERROR"
    change = client.patch(
        f"/api/workspace/members/{member.user_id}",
        json={"role": "legal_reviewer"},
        headers=owner.headers,
    )
    assert change.status_code == 403 and _code(change) == "ROLE_ESCALATION_FORBIDDEN"


def test_nobody_changes_their_own_role(client, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    response = client.patch(
        f"/api/workspace/members/{owner.user_id}", json={"role": "writer"}, headers=owner.headers
    )
    assert response.status_code == 403
    assert _code(response) == "SELF_ROLE_CHANGE_FORBIDDEN"


def test_last_owner_cannot_be_removed_or_demoted(client, account_factory, db_session) -> None:
    owner = account_factory("owner", with_source=False)
    second = account_factory("second", with_source=False)

    alone = client.delete(f"/api/workspace/members/{owner.user_id}", headers=owner.headers)
    assert alone.status_code == 409 and _code(alone) == "LAST_OWNER_REQUIRED"

    _join(client, owner, second, "approver")
    promoted = client.patch(
        f"/api/workspace/members/{second.user_id}", json={"role": "owner"}, headers=owner.headers
    )
    assert promoted.status_code == 200 and promoted.json()["role"] == "owner"

    # Now two owners: the second may demote the first, but then can't demote themself away.
    demoted = client.patch(
        f"/api/workspace/members/{owner.user_id}", json={"role": "reviewer"}, headers=second.headers
    )
    assert demoted.status_code == 200, demoted.text
    leave = client.delete(f"/api/workspace/members/{second.user_id}", headers=second.headers)
    assert leave.status_code == 409 and _code(leave) == "LAST_OWNER_REQUIRED"

    changes = _events(db_session, owner.organisation_id, "member_role_changed")
    assert sorted((e.details["before"]["role"], e.details["after"]["role"]) for e in changes) == [
        ("approver", "owner"),
        ("owner", "reviewer"),
    ]


def test_removed_member_loses_access_at_once_and_can_be_reinvited(
    client, account_factory, db_session
) -> None:
    owner = account_factory("owner", with_source=False)
    member = account_factory("member", with_source=False)
    personal_token = member.token
    _join(client, owner, member, "approver")

    removed = client.delete(f"/api/workspace/members/{member.user_id}", headers=owner.headers)
    assert removed.status_code == 200, removed.text
    assert removed.json()["role"] == "approver"
    assert client.get("/api/auth/me", headers=member.headers).status_code == 401
    roster = client.get("/api/workspace/members", headers=owner.headers).json()["members"]
    assert [m["user"]["id"] for m in roster] == [owner.user_id]
    events = _events(db_session, owner.organisation_id, "member_removed")
    assert [e.details for e in events] == [
        {"user_id": member.user_id, "before": {"role": "approver"}}
    ]

    # Their personal workspace is untouched; from there they can come back in with only the
    # newly invited role.
    member.token = personal_token
    assert client.get("/api/auth/me", headers=member.headers).status_code == 200
    session = _join(client, owner, member, "writer")
    assert session["role"] == "writer"


# --- Tenant isolation --------------------------------------------------------------------------


def test_outsider_cannot_touch_another_workspace(client, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    member = account_factory("member", with_source=False)
    outsider = account_factory("outsider", with_source=False)
    _join(client, owner, member, "writer")
    pending = _invite(client, owner, "pending@example.com").json()["invitation"]["id"]

    # The outsider owns their own workspace, so every refusal here is "not in yours" (404).
    for response in (
        client.post(f"/api/workspace/invitations/{pending}/revoke", headers=outsider.headers),
        client.patch(
            f"/api/workspace/members/{member.user_id}",
            json={"role": "owner"},
            headers=outsider.headers,
        ),
        client.delete(f"/api/workspace/members/{member.user_id}", headers=outsider.headers),
        client.post(
            "/api/auth/switch-workspace",
            json={"workspace_id": owner.organisation_id},
            headers=outsider.headers,
        ),
    ):
        assert response.status_code == 404, response.text
        assert _code(response) == "NOT_FOUND"

    own = client.get("/api/workspace/invitations", headers=outsider.headers).json()["items"]
    assert own == []
    roster = client.get("/api/workspace/members", headers=outsider.headers).json()["members"]
    assert [m["user"]["id"] for m in roster] == [outsider.user_id]
