"""Permission rules in individual-user mode (product decision 2026-10-24). No database needed.

Previously this file pinned a role -> permission matrix (submitter could only submit, reviewer
could not approve, ...). InkLoom is now a one-person-per-account app: every active membership is
the account owner and holds every permission, whatever role string it carries (registration
writes "admin", which now just means "account owner"). Access between accounts is enforced by
tenant scoping (test_cross_account_isolation.py, test_tenant_scoping.py), not by roles.
"""

from __future__ import annotations

import uuid

import pytest

from inkloom_api.auth.dependencies import AuthContext
from inkloom_api.auth.permissions import Permission, role_has_permission
from inkloom_api.models import Membership, Organisation, User
from inkloom_api.statuses import MembershipRole


@pytest.mark.parametrize("role", [r.value for r in MembershipRole])
@pytest.mark.parametrize("permission", list(Permission))
def test_every_known_role_holds_every_permission(role: str, permission: Permission) -> None:
    assert role_has_permission(role, permission) is True


def test_unknown_role_has_no_permissions() -> None:
    """Defensive default; the memberships.role CHECK constraint already prevents this value."""
    assert role_has_permission("superuser", Permission.SUBMIT) is False


def _auth_context(role: str) -> AuthContext:
    user = User(id=uuid.uuid4(), email="u@example.com")
    org = Organisation(id=uuid.uuid4(), name="Acme", slug="acme")
    membership = Membership(id=uuid.uuid4(), organisation_id=org.id, user_id=user.id, role=role, is_active=True)
    return AuthContext(user=user, organisation=org, membership=membership)


@pytest.mark.parametrize("role", ["admin", "submitter", "reviewer"])
def test_account_owner_may_approve_whatever_role_string_it_has(role: str) -> None:
    _auth_context(role).require(Permission.APPROVE)  # must not raise
    _auth_context(role).require(Permission.MANAGE_SOURCES)  # must not raise
