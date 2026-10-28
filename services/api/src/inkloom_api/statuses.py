"""Every status string the backend defines, in one place.

Mirrors how Member 2 keeps `inkloom_verify/schemas.py` as the single source for the engine's
enums. `contract/README.md` is hand-maintained to match these values and the CHECK constraints
in `migrations/versions/0001_initial_schema.py` — there is no generator (unlike Member 2's
`json_schema.py`); keep all three in sync by hand when a value here changes.
"""

from __future__ import annotations

from enum import Enum


class VerificationStatus(str, Enum):
    """Shared contract value (docs/backend.md). Missing evidence means UNVERIFIED, never FALSE."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"
    CONFLICTING_SOURCES = "conflicting_sources"
    NOT_APPLICABLE = "not_applicable"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class ReviewState(str, Enum):
    """`completed` never means approved. See the governance invariants in docs/backend.md."""

    DRAFT = "draft"
    QUEUED = "queued"
    ANALYSING = "analysing"
    COMPLETED = "completed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    SOURCE_CHANGED = "source_changed"


class FindingCategory(str, Enum):
    """`findings.category` for engine findings (free-form column, no CHECK constraint). The
    Insights page groups by this. `STUB` marks the placeholder written when no provider is
    configured; every real run sets one of the other four from the claim's verdict."""

    STUB = "stub"
    CONTRADICTED_CLAIM = "contradicted_claim"
    UNSUPPORTED_CLAIM = "unsupported_claim"  # unverified: no evidence either way
    SUPPORTED_CLAIM = "supported_claim"
    ENGINE_ERROR = "engine_error"  # this one claim could not be checked (provider/engine failure)
    # Rule findings (check_type "rule") carry the engine's own rule category instead:
    # "terminology", "brand_compliance" or "accessibility" (inkloom_verify.schemas.RuleCategory).


class RulesStatus(str, Enum):
    """`reviews.rules_status` (migration 0010): whether the brand's rules ran on this review.
    NULL on reviews from before rules were wired in."""

    COMPLETE = "complete"  # every rule check ran (each one passed, violated or not_checkable)
    INCOMPLETE = (
        "incomplete"  # at least one check ended in error: never show the draft as rule-clean
    )
    NOT_APPLIED = (
        "not_applied"  # nothing ran: the stored rules are invalid, or the rules engine failed
    )


class CheckType(str, Enum):
    RULE = "rule"
    RETRIEVAL = "retrieval"
    SEMANTIC = "semantic"


class BrandSourceStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class BrandSourceSensitivity(str, Enum):
    NORMAL = "normal"
    CONFIDENTIAL = "confidential"


class SourceFileType(str, Enum):
    """What kind of file a brand source was uploaded as (Phase 4 task 3). Member 1's Brand
    Knowledge screen shows this as the source's "type"."""

    TXT = "txt"
    PDF = "pdf"
    DOCX = "docx"


class MembershipRole(str, Enum):
    """Role names agreed with the team. Permissions for each role live in `auth/permissions.py`,
    not here — this module is only the stable set of names enforced by the `memberships.role`
    CHECK constraint.

    `LEGAL_REVIEWER` and `BRAND_MANAGER` added for Phase 9 stretch item 1 (risk-based approval
    routing, see `reviews.required_reviewer_role` and `approval_rules.ensure_role_matches_
    routing`) — a real contract change (new role names), confirmed with the team before adding,
    not assumed.

    Round 3 workspaces (migration 0014, docs/governance.md): the four team roles are `OWNER`,
    `APPROVER`, `REVIEWER` and `WRITER`. Registration makes the user `OWNER` of their personal
    workspace, and invitations grant one of the four. The older names stay valid so existing rows
    keep working; `auth/permissions.py` maps each one onto a team role (`ADMIN` means owner)."""

    OWNER = "owner"
    WRITER = "writer"
    SUBMITTER = "submitter"
    SOURCE_MANAGER = "source_manager"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    ADMIN = "admin"
    LEGAL_REVIEWER = "legal_reviewer"
    BRAND_MANAGER = "brand_manager"


TEAM_ROLES = (
    MembershipRole.OWNER,
    MembershipRole.APPROVER,
    MembershipRole.REVIEWER,
    MembershipRole.WRITER,
)
"""The roles an invitation or a role change may grant (`invitations.role` CHECK)."""


class InvitationStatus(str, Enum):
    """Derived from an invitation's timestamps, never stored."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ApprovalAction(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class EvaluationRunStatus(str, Enum):
    """`evaluation_runs.status` (migration 0009). PARTIAL: some claims got no verdict (a provider
    failure or the run's call budget) - they count as "not flagged" and the note says so."""

    COMPLETED = "completed"
    PARTIAL = "partial"


class ExternalCallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


def values(enum_cls: type[Enum]) -> list[str]:
    return [member.value for member in enum_cls]
