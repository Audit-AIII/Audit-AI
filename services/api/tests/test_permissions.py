"""Unit tests for the permission table (phase2_auth_and_tenant_scoping.md task 3) and the
AuthContext.require() check that enforces it. No database needed: this is pure logic.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from inkloom_api.auth.dependencies import AuthContext
from inkloom_api.auth.permissions import Permission, role_has_permission
from inkloom_api.models import Membership, Organisation, User


@pytest.mark.parametrize(
    "role,permission,expected",
    [
        ("submitter", Permission.SUBMIT, True),
        ("submitter", Permission.APPROVE, False),
        ("submitter", Permission.MANAGE_SOURCES, False),
        ("source_manager", Permission.MANAGE_SOURCES, True),
        ("source_manager", Permission.SUBMIT, False),
        ("reviewer", Permission.REVIEW, True),
        ("reviewer", Permission.APPROVE, False),
        ("approver", Permission.REVIEW, True),
        ("approver", Permission.APPROVE, True),
        ("approver", Permission.MANAGE_SOURCES, False),
        ("admin", Permission.SUBMIT, True),
        ("admin", Permission.MANAGE_SOURCES, True),
        ("admin", Permission.REVIEW, True),
        ("admin", Permission.APPROVE, True),
        ("admin", Permission.ADMINISTER, True),
    ],
)
def test_role_has_permission_matrix(role: str, permission: Permission, expected: bool) -> None:
    assert role_has_permission(role, permission) is expected


def test_unknown_role_has_no_permissions() -> None:
    assert role_has_permission("superuser", Permission.SUBMIT) is False


def _auth_context(role: str) -> AuthContext:
    user = User(id=uuid.uuid4(), email="u@example.com")
    org = Organisation(id=uuid.uuid4(), name="Acme", slug="acme")
    membership = Membership(id=uuid.uuid4(), organisation_id=org.id, user_id=user.id, role=role, is_active=True)
    return AuthContext(user=user, organisation=org, membership=membership)


def test_submitter_cannot_escalate_to_approve() -> None:
    """A submitter trying to use an approver-only action is denied with a safe 403, not granted
    just because it asked (the "role escalation attempts are denied" test, task 20)."""
    ctx = _auth_context("submitter")
    with pytest.raises(HTTPException) as exc_info:
        ctx.require(Permission.APPROVE)
    assert exc_info.value.status_code == 403
    assert "approve" in exc_info.value.detail
    assert "submitter" not in exc_info.value.detail  # message names the permission, not the role


def test_approver_can_approve() -> None:
    _auth_context("approver").require(Permission.APPROVE)  # must not raise
