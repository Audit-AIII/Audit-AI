"""The Round 3 role x action matrix (docs/governance.md section 5). No database needed.

The expected table below is written out by hand, independently of `auth/permissions.py`'s own
`_GRANTS`, so changing who may do what there fails here until the documented matrix agrees.
Route-level behaviour (the same rules through real HTTP calls) is in test_governance_roles.py.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from inkloom_api.auth.dependencies import AuthContext
from inkloom_api.auth.permissions import (
    Permission,
    allowed_review_actions,
    can,
    role_has_permission,
    team_role,
)
from inkloom_api.models import Membership, Organisation, User

P = Permission
EXPECTED: dict[Permission, set[str]] = {
    P.CREATE_BRAND: {"approver", "owner"},
    P.MANAGE_SOURCES: {"approver", "owner"},
    P.EDIT_RULES: {"approver", "owner"},
    P.CREATE_CONTENT: {"writer", "owner"},
    P.EDIT_CONTENT: {"writer", "owner"},
    P.RERUN: {"writer", "reviewer", "approver", "owner"},
    P.COMMENT: {"writer", "reviewer", "approver", "owner"},
    P.DISMISS_FINDING: {"reviewer", "approver", "owner"},
    P.REQUEST_CHANGES: {"reviewer", "approver", "owner"},
    P.APPROVE: {"approver", "owner"},
    P.REJECT: {"approver", "owner"},
    P.RUN_EVALUATION: {"owner"},
    P.MANAGE_MEMBERS: {"owner"},
}
TEAM_ROLES = ("owner", "approver", "reviewer", "writer")
LEGACY = {
    "admin": "owner",
    "submitter": "writer",
    "source_manager": "writer",
    "legal_reviewer": "reviewer",
    "brand_manager": "approver",
}


def test_matrix_covers_every_permission() -> None:
    assert set(EXPECTED) == set(Permission)


@pytest.mark.parametrize("role", TEAM_ROLES)
@pytest.mark.parametrize("permission", list(Permission))
def test_role_matrix(role: str, permission: Permission) -> None:
    assert role_has_permission(role, permission) is (role in EXPECTED[permission])


@pytest.mark.parametrize(("legacy", "mapped"), sorted(LEGACY.items()))
def test_legacy_roles_get_exactly_their_team_roles_powers(legacy: str, mapped: str) -> None:
    assert team_role(legacy).value == mapped
    for permission in Permission:
        assert role_has_permission(legacy, permission) is role_has_permission(mapped, permission)


def test_unknown_role_has_no_permissions() -> None:
    assert team_role("superuser") is None
    assert not any(role_has_permission("superuser", p) for p in Permission)


def _item(author: uuid.UUID | None):
    return SimpleNamespace(created_by=author)


def test_writer_edits_and_rechecks_only_their_own_drafts() -> None:
    me, other = uuid.uuid4(), uuid.uuid4()
    for permission in (P.EDIT_CONTENT, P.RERUN):
        assert can("writer", me, permission, _item(me))
        assert not can("writer", me, permission, _item(other))
        assert not can("writer", me, permission, _item(None))  # no author recorded
        assert can("owner", me, permission, _item(other))
    assert can("reviewer", me, P.RERUN, _item(other))


def _auth_context(role: str) -> AuthContext:
    user = User(id=uuid.uuid4(), email="u@example.com")
    org = Organisation(id=uuid.uuid4(), name="Acme", slug="acme")
    membership = Membership(
        id=uuid.uuid4(), organisation_id=org.id, user_id=user.id, role=role, is_active=True
    )
    return AuthContext(user=user, organisation=org, membership=membership)


def test_require_refuses_with_a_safe_403() -> None:
    auth = _auth_context("writer")
    auth.require(P.CREATE_CONTENT)  # must not raise
    with pytest.raises(HTTPException) as refused:
        auth.require(P.APPROVE)
    assert refused.value.status_code == 403
    assert refused.value.detail == "your role in this workspace cannot approve content"
    with pytest.raises(HTTPException):
        auth.require(P.EDIT_CONTENT, _item(uuid.uuid4()))  # someone else's draft


_ACTION_PERMISSION = {
    "create_version": P.EDIT_CONTENT,
    "rerun": P.RERUN,
    "approve": P.APPROVE,
    "request_changes": P.REQUEST_CHANGES,
    "reject": P.REJECT,
    "comment": P.COMMENT,
    "dismiss_finding": P.DISMISS_FINDING,
}


@pytest.mark.parametrize("role", TEAM_ROLES)
@pytest.mark.parametrize("own", [True, False])
def test_allowed_actions_on_a_current_decidable_review_follow_can(role: str, own: bool) -> None:
    me = uuid.uuid4()
    item = _item(me if own else uuid.uuid4())
    actions = allowed_review_actions(
        role, me, item, "needs_human_review", is_latest_review=True, is_current_version=True
    )
    assert set(actions) == {
        name for name, permission in _ACTION_PERMISSION.items() if can(role, me, permission, item)
    }


def test_writer_never_gets_approve_on_their_own_draft() -> None:
    me = uuid.uuid4()
    actions = allowed_review_actions(
        "writer", me, _item(me), "completed", is_latest_review=True, is_current_version=True
    )
    assert actions == ["create_version", "rerun", "comment"]


def test_decisions_only_on_the_latest_decidable_review() -> None:
    me = uuid.uuid4()

    def actions(status, latest, current):
        return allowed_review_actions(
            "owner",
            me,
            _item(me),
            status,
            is_latest_review=latest,
            is_current_version=current,
        )

    assert {"approve", "request_changes", "reject"} <= set(actions("completed", True, True))
    # An older version's latest review: still sent back / rejected by its route, never approved.
    assert "approve" not in actions("completed", True, False)
    assert {"request_changes", "reject"} <= set(actions("completed", True, False))
    for status, latest in (("approved", True), ("failed", True), ("completed", False)):
        assert not {"approve", "request_changes", "reject"} & set(actions(status, latest, True))
    assert {"create_version", "rerun", "comment", "dismiss_finding"} <= set(
        actions("failed", False, False)
    )
