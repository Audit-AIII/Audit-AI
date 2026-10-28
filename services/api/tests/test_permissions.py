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
    P.SUBMIT: {"writer", "owner"},
    P.ASSIGN: {"reviewer", "approver", "owner"},
    P.MARK_REVIEWED: {"reviewer", "owner"},
    P.PUBLISH: {"approver", "owner"},
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


def _item(
    author: uuid.UUID | None,
    status: str = "submitted",
    routing: str | None = "approver",
    risk: str | None = "clean",
    reviewed_by: uuid.UUID | None = None,
):
    """A draft as `allowed_review_actions` reads it."""
    return SimpleNamespace(
        created_by=author,
        workflow_status=status,
        required_reviewer_role=routing,
        risk_level=risk,
        reviewed_by=reviewed_by,
        submitted_at=None,
    )


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
    "assign": P.ASSIGN,
    "approve": P.APPROVE,
    "request_changes": P.REQUEST_CHANGES,
    "reject": P.REJECT,
    "comment": P.COMMENT,
    "dismiss_finding": P.DISMISS_FINDING,
}


def _actions(role, user, item, review_status="completed", **kw) -> list[str]:
    kw.setdefault("is_latest_review", True)
    kw.setdefault("is_current_version", True)
    return allowed_review_actions(role, user, item, review_status, **kw)


@pytest.mark.parametrize("role", TEAM_ROLES)
@pytest.mark.parametrize("own", [True, False])
def test_allowed_actions_on_a_submitted_clean_draft_follow_can(role: str, own: bool) -> None:
    """A clean draft waiting for an approver: every action the role holds, except approving
    your own work (Phase 3)."""
    me = uuid.uuid4()
    item = _item(me if own else uuid.uuid4())
    expected = {
        name for name, permission in _ACTION_PERMISSION.items() if can(role, me, permission, item)
    }
    if own:
        expected.discard("approve")
    assert set(_actions(role, me, item, "needs_human_review")) == expected


def test_writer_never_gets_approve_on_their_own_draft() -> None:
    me = uuid.uuid4()
    draft = _item(me, status="draft", routing="reviewer", risk="medium")
    assert _actions("writer", me, draft) == ["create_version", "rerun", "submit", "comment"]


def test_decisions_only_on_the_latest_review_of_the_current_version() -> None:
    me = uuid.uuid4()
    item = _item(uuid.uuid4())

    def actions(status, latest, current):
        return set(
            _actions("owner", me, item, status, is_latest_review=latest, is_current_version=current)
        )

    assert {"approve", "request_changes", "reject"} <= actions("completed", True, True)
    for status, latest, current in (
        ("completed", True, False),  # an older version
        ("completed", False, True),  # superseded by a re-check
        ("approved", True, True),
        ("failed", True, True),
    ):
        assert not {"approve", "request_changes", "reject"} & actions(status, latest, current)
    assert {"create_version", "rerun", "comment", "dismiss_finding"} <= actions(
        "failed", False, False
    )


def test_approve_on_own_work_only_as_a_solo_sign_off() -> None:
    me, writer = uuid.uuid4(), uuid.uuid4()

    def approve_listed(item, version=None, solo=False) -> bool:
        return "approve" in _actions(
            "owner", me, item, content_version=version, self_approval_allowed=solo
        )

    assert approve_listed(_item(writer))
    assert not approve_listed(_item(me))
    assert not approve_listed(_item(writer), version=_item(me))  # I wrote this version
    assert approve_listed(_item(me), solo=True)


def test_workflow_state_decides_which_actions_are_offered() -> None:
    me, writer = uuid.uuid4(), uuid.uuid4()
    risky_draft = _item(writer, status="draft", routing="reviewer", risk="high")
    clean_draft = _item(writer, status="draft", routing="approver", risk="clean")
    in_review = _item(writer, status="in_review", routing="reviewer", risk="high")

    # D4: a clean draft can be approved straight away (it is submitted first); a risky one can't.
    assert "approve" in _actions("approver", me, clean_draft)
    assert "approve" not in _actions("approver", me, risky_draft)
    assert {"request_changes", "reject"} <= set(_actions("approver", me, risky_draft))
    # In review: the reviewer marks it reviewed; nobody approves yet - unless a solo approver's
    # approval stands in for the review (P4).
    assert "mark_reviewed" in _actions("reviewer", me, in_review)
    assert "approve" not in _actions("approver", me, in_review)
    assert "approve" in _actions("owner", me, in_review, solo_review_shortcut=True)
    # D6: the author doesn't review their own draft, unless nobody else could.
    own_in_review = _item(me, status="in_review", routing="reviewer", risk="high")
    assert "mark_reviewed" not in _actions("owner", me, own_in_review)
    assert "mark_reviewed" in _actions("owner", me, own_in_review, self_review_allowed=True)
    # D6: whoever marked it reviewed doesn't approve it, unless nobody else could.
    reviewed_by_me = _item(
        writer, status="reviewed", routing="reviewer", risk="high", reviewed_by=me
    )
    assert "approve" not in _actions("owner", me, reviewed_by_me)
    assert "approve" in _actions("owner", me, reviewed_by_me, self_approval_allowed=True)
    assert "approve" in _actions(
        "approver", me, _item(writer, status="reviewed", reviewed_by=writer)
    )
    # Approved content is published by someone other than its author.
    approved = _item(writer, status="approved")
    assert "publish" in _actions("approver", me, approved)
    assert "publish" not in _actions("approver", writer, approved)
    assert not {"approve", "request_changes", "reject"} & set(_actions("owner", me, approved))
    # Blocked: only re-check (and edit / comment / dismiss).
    blocked = _item(writer, status="blocked", routing=None, risk=None)
    assert set(_actions("owner", me, blocked)) == {
        "create_version",
        "rerun",
        "comment",
        "dismiss_finding",
    }
