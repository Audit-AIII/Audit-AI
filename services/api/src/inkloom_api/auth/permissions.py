"""The permission table from phase2_auth_and_tenant_scoping.md task 3, confirmed with the team.

One role per permission; `admin` holds every permission so one person can run a brand-new
organisation alone. See contract/README.md, "Role names", for the same table in doc form.
"""

from __future__ import annotations

from enum import Enum

from ..statuses import MembershipRole


class Permission(str, Enum):
    SUBMIT = "submit"
    MANAGE_SOURCES = "manage_sources"
    REVIEW = "review"
    APPROVE = "approve"
    ADMINISTER = "administer"


ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.SUBMITTER: frozenset({Permission.SUBMIT}),
    MembershipRole.SOURCE_MANAGER: frozenset({Permission.MANAGE_SOURCES}),
    MembershipRole.REVIEWER: frozenset({Permission.REVIEW}),
    MembershipRole.APPROVER: frozenset({Permission.REVIEW, Permission.APPROVE}),
    MembershipRole.ADMIN: frozenset(Permission),
    # Phase 9 stretch item 1: same raw permissions as APPROVER (review + approve) - what
    # actually restricts each to its own risk tier is approval_rules.ensure_role_matches_routing,
    # not this table. This table only answers "can this role ever approve anything" (yes); the
    # routing guard answers "can this role approve THIS review."
    MembershipRole.LEGAL_REVIEWER: frozenset({Permission.REVIEW, Permission.APPROVE}),
    MembershipRole.BRAND_MANAGER: frozenset({Permission.REVIEW, Permission.APPROVE}),
}


def role_has_permission(role: str, permission: Permission) -> bool:
    try:
        role_enum = MembershipRole(role)
    except ValueError:
        return False
    return permission in ROLE_PERMISSIONS.get(role_enum, frozenset())
