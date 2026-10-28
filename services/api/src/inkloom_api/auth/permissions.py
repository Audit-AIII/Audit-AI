"""The one place that decides who may do what (Round 3, docs/governance.md section 5).

A membership has one role. The four team roles are owner, approver, reviewer and writer; every
older role name maps onto one of them (`team_role`), so rows written before migration 0014 keep
working. `Permission` names each action a route can take; `_GRANTS` is the role x action table.

Two layers, both here:

- `role_has_permission(role, permission)`: may this role ever do it? Routes check this first
  through `require_permission(...)` (auth/dependencies.py), before loading anything.
- `can(role, user_id, permission, content_item)`: may this person do it to this draft? Adds the
  "own drafts only" rule for writers. Routes that act on a draft call `auth.require(permission,
  item)` once the draft is loaded (tenant-scoped, so another workspace's draft is a 404 first).

`allowed_review_actions` builds a review's `allowed_actions[]` from `can` and nothing else, so
the list the frontend gets never disagrees with what the server enforces.

What protects data across workspaces is not a role check: the membership must be active
(auth/dependencies.py) and every lookup is scoped to the token's own workspace (tenancy.py).
"""

from __future__ import annotations

import uuid
from enum import Enum

from ..statuses import TEAM_ROLES, MembershipRole, ReviewState


class Permission(str, Enum):
    CREATE_BRAND = "create_brand"
    MANAGE_SOURCES = "manage_sources"
    EDIT_RULES = "edit_rules"
    CREATE_CONTENT = "create_content"
    EDIT_CONTENT = "edit_content"
    RERUN = "rerun"
    COMMENT = "comment"
    DISMISS_FINDING = "dismiss_finding"
    REQUEST_CHANGES = "request_changes"
    APPROVE = "approve"
    REJECT = "reject"
    RUN_EVALUATION = "run_evaluation"
    MANAGE_MEMBERS = "manage_members"


_W, _R, _A, _O = (
    MembershipRole.WRITER,
    MembershipRole.REVIEWER,
    MembershipRole.APPROVER,
    MembershipRole.OWNER,
)

# Reading anything in the workspace needs only an active membership, so it is not listed here.
_GRANTS: dict[Permission, frozenset[MembershipRole]] = {
    Permission.CREATE_BRAND: frozenset({_A, _O}),
    Permission.MANAGE_SOURCES: frozenset({_A, _O}),
    Permission.EDIT_RULES: frozenset({_A, _O}),
    Permission.CREATE_CONTENT: frozenset({_W, _O}),
    Permission.EDIT_CONTENT: frozenset({_W, _O}),
    Permission.RERUN: frozenset({_W, _R, _A, _O}),
    Permission.COMMENT: frozenset({_W, _R, _A, _O}),
    Permission.DISMISS_FINDING: frozenset({_R, _A, _O}),
    Permission.REQUEST_CHANGES: frozenset({_R, _A, _O}),
    Permission.APPROVE: frozenset({_A, _O}),
    Permission.REJECT: frozenset({_A, _O}),
    Permission.RUN_EVALUATION: frozenset({_O}),
    Permission.MANAGE_MEMBERS: frozenset({_O}),
}

# A writer may do these only to drafts they wrote.
_OWN_DRAFTS_ONLY: dict[MembershipRole, frozenset[Permission]] = {
    _W: frozenset({Permission.EDIT_CONTENT, Permission.RERUN}),
}

# Plain-language verbs for the 403 message.
_VERB = {
    Permission.CREATE_BRAND: "create brands",
    Permission.MANAGE_SOURCES: "change brand documents",
    Permission.EDIT_RULES: "change brand rules",
    Permission.CREATE_CONTENT: "create drafts",
    Permission.EDIT_CONTENT: "edit this draft",
    Permission.RERUN: "re-check this draft",
    Permission.COMMENT: "comment",
    Permission.DISMISS_FINDING: "dismiss findings",
    Permission.REQUEST_CHANGES: "send drafts back",
    Permission.APPROVE: "approve content",
    Permission.REJECT: "reject content",
    Permission.RUN_EVALUATION: "run evaluations",
    Permission.MANAGE_MEMBERS: "manage members and invitations",
}

_LEGACY_TEAM_ROLE = {
    MembershipRole.ADMIN.value: _O,
    MembershipRole.SUBMITTER.value: _W,
    MembershipRole.SOURCE_MANAGER.value: _W,
    MembershipRole.LEGAL_REVIEWER.value: _R,
    MembershipRole.BRAND_MANAGER.value: _A,
}
_TEAM_ROLE_VALUES = frozenset(role.value for role in TEAM_ROLES)


def team_role(role: str) -> MembershipRole | None:
    """The team role a stored role string means, or None for an unknown string (which the
    `memberships.role` CHECK constraint already prevents)."""
    if role in _TEAM_ROLE_VALUES:
        return MembershipRole(role)
    return _LEGACY_TEAM_ROLE.get(role)


def is_owner(role: str) -> bool:
    return team_role(role) is _O


def role_has_permission(role: str, permission: Permission) -> bool:
    """Whether this role may ever take this action (on at least its own drafts). An unknown role
    has no permissions."""
    mapped = team_role(role)
    return mapped is not None and mapped in _GRANTS[permission]


def is_own_draft(content_item, user_id: uuid.UUID) -> bool:
    return content_item is not None and content_item.created_by == user_id


def is_author(user_id: uuid.UUID, content_item, content_version=None) -> bool:
    """Wrote the draft, or wrote the version in question (an owner who edited someone else's
    draft authored that version). Used by the self-approval rule (approval_service.py)."""
    authors = {
        getattr(content_item, "created_by", None),
        getattr(content_version, "created_by", None),
    }
    return user_id in authors


def can(role: str, user_id: uuid.UUID, permission: Permission, content_item=None) -> bool:
    """Whether this person may take this action, on this draft when one is given."""
    if not role_has_permission(role, permission):
        return False
    if permission in _OWN_DRAFTS_ONLY.get(team_role(role), frozenset()):
        return is_own_draft(content_item, user_id)
    return True


def forbidden_message(permission: Permission) -> str:
    return f"your role in this workspace cannot {_VERB[permission]}"


def can_manage_members(role: str) -> bool:
    return role_has_permission(role, Permission.MANAGE_MEMBERS)


def can_grant_role(granter_role: str, role: str) -> bool:
    """Nobody grants a role above their own. Owners hold every role, and only owners manage
    members, so in practice an owner may grant any of the four team roles and nobody else may
    grant any. Only the four team roles can be granted, never a legacy name."""
    return role in _TEAM_ROLE_VALUES and is_owner(granter_role)


_DECIDABLE = frozenset({ReviewState.COMPLETED.value, ReviewState.NEEDS_HUMAN_REVIEW.value})


def allowed_review_actions(
    role: str,
    user_id: uuid.UUID,
    content_item,
    review_status: str,
    *,
    is_latest_review: bool,
    is_current_version: bool,
    content_version=None,
    self_approval_allowed: bool = False,
) -> list[str]:
    """`allowed_actions[]` for one review, as the frontend gets it (docs/governance.md 9.2), with
    exactly the conditions the routes apply:

    - approve: the latest review of the draft's current version, in a decidable state (the
      approve route refuses anything else as stale or not decidable), and never to the draft's
      or version's author unless `self_approval_allowed` (D1: nobody else could approve);
    - request_changes / reject: the latest review of its version, decidable;
    - create_version, rerun, comment, dismiss_finding: any review (their routes don't care which).
    """

    def ok(permission: Permission) -> bool:
        return can(role, user_id, permission, content_item)

    decidable = is_latest_review and review_status in _DECIDABLE
    actions: list[str] = []
    if ok(Permission.EDIT_CONTENT):
        actions.append("create_version")
    if ok(Permission.RERUN):
        actions.append("rerun")
    own_work = is_author(user_id, content_item, content_version)
    if (
        decidable
        and is_current_version
        and ok(Permission.APPROVE)
        and (self_approval_allowed or not own_work)
    ):
        actions.append("approve")
    if decidable and ok(Permission.REQUEST_CHANGES):
        actions.append("request_changes")
    if decidable and ok(Permission.REJECT):
        actions.append("reject")
    if ok(Permission.COMMENT):
        actions.append("comment")
    if ok(Permission.DISMISS_FINDING):
        actions.append("dismiss_finding")
    return actions
