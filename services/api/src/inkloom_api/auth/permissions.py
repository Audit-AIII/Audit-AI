"""Permission names, team roles, and the rule that decides who holds them.

Round 3 workspaces (docs/governance.md): a membership has one role. The four team roles are
owner, approver, reviewer and writer; every older role name maps onto one of them (`team_role`),
so rows written before migration 0014 keep working.

Phase 1 enforces workspace management here (`can_manage_members`, `can_grant_role`). Content
routes still pass for every known role through `role_has_permission` until Phase 2 replaces it
with the full role x action table in this same module, so there stays one place to change.

What protects data across workspaces is unchanged and is not a role check: the membership must
be active (auth/dependencies.py) and every lookup is scoped to the token's own workspace
(tenancy.py).
"""

from __future__ import annotations

from enum import Enum

from ..statuses import TEAM_ROLES, MembershipRole


class Permission(str, Enum):
    SUBMIT = "submit"
    MANAGE_SOURCES = "manage_sources"
    REVIEW = "review"
    APPROVE = "approve"
    ADMINISTER = "administer"


_KNOWN_ROLES = frozenset(role.value for role in MembershipRole)

_LEGACY_TEAM_ROLE = {
    MembershipRole.ADMIN.value: MembershipRole.OWNER,
    MembershipRole.SUBMITTER.value: MembershipRole.WRITER,
    MembershipRole.SOURCE_MANAGER.value: MembershipRole.WRITER,
    MembershipRole.LEGAL_REVIEWER.value: MembershipRole.REVIEWER,
    MembershipRole.BRAND_MANAGER.value: MembershipRole.APPROVER,
}
_TEAM_ROLE_VALUES = frozenset(role.value for role in TEAM_ROLES)


def team_role(role: str) -> MembershipRole | None:
    """The team role a stored role string means, or None for an unknown string (which the
    `memberships.role` CHECK constraint already prevents)."""
    if role in _TEAM_ROLE_VALUES:
        return MembershipRole(role)
    return _LEGACY_TEAM_ROLE.get(role)


def is_owner(role: str) -> bool:
    return team_role(role) is MembershipRole.OWNER


def can_manage_members(role: str) -> bool:
    """Invite, revoke invitations, change roles, remove members: owners only."""
    return is_owner(role)


def can_grant_role(granter_role: str, role: str) -> bool:
    """Nobody grants a role above their own. Owners hold every role, and only owners manage
    members, so in practice an owner may grant any of the four team roles and nobody else may
    grant any. Only the four team roles can be granted, never a legacy name."""
    return role in _TEAM_ROLE_VALUES and is_owner(granter_role)


def role_has_permission(role: str, permission: Permission) -> bool:
    """True for every known role until Phase 2 (see the module docstring). An unknown role string
    is still refused, as a defensive default."""
    return role in _KNOWN_ROLES and isinstance(permission, Permission)
