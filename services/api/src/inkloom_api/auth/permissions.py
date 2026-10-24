"""Permission names, and the rule that decides who holds them.

Individual-user mode (product decision, 2026-10-24): InkLoom is a one-person-per-account app.
Every organisation is one user's private account, and that user owns everything in it - there
are no teammates, reviewer tiers or admins-vs-others. So a role no longer gates anything: every
active membership holds every permission. Registration still writes `role="admin"`, which now
simply means "account owner"; the other role names stay valid (the `memberships.role` CHECK
constraint and migration 0008 are unchanged) so no data or migration has to move, but they grant
exactly the same as `admin`.

What still protects data is unchanged and is not a role check: the membership must be active
(auth/dependencies.py) and every lookup is scoped to the membership's own organisation
(tenancy.py). `Permission` and `require_permission(...)` stay on every route so the intent of each
route is still readable, and so a future multi-user mode has one place to change.
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


_KNOWN_ROLES = frozenset(role.value for role in MembershipRole)


def role_has_permission(role: str, permission: Permission) -> bool:
    """True for every known role: the member is the account owner. An unknown role string (which
    the database CHECK constraint already prevents) is still refused, as a defensive default."""
    return role in _KNOWN_ROLES and isinstance(permission, Permission)
