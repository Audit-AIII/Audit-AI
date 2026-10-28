"""Workflow state machine for a draft (Round 3 Phase 4, docs/governance.md section 6).

Pure logic, no DB and no FastAPI, like `approval_rules.py`: each function answers "is this
transition allowed from this state?" and, when it isn't, which error code says why. Both the
routes (workflow.py) and `allowed_actions` (auth/permissions.py) ask these same functions, so the
two can never disagree.

    draft --submit--> in_review (reviewer needed) | submitted (clean: approver only)
    in_review --mark_reviewed--> reviewed            in_review --request_changes--> needs_changes
    submitted | reviewed --approve--> approved --publish--> published
    draft | submitted | in_review | reviewed --reject--> rejected
    draft | submitted | reviewed --request_changes--> needs_changes
    a new version from any state --> draft;  a failed check or changed source --> blocked

Decision D4: approve, send back and reject on a `draft` submit it first (routing runs), in the
same transaction - so a draft that needs a reviewer is refused with REVIEW_REQUIRED on approve.
"""

from __future__ import annotations

from .errors import ErrorCode
from .risk_policy import APPROVER
from .statuses import WorkflowStatus as S

_PRE_DECISION = frozenset({S.DRAFT, S.SUBMITTED, S.IN_REVIEW, S.REVIEWED})


def _status(value: str | None) -> S | None:
    try:
        return S(value)
    except ValueError:
        return None


def submit_error(status: str) -> ErrorCode | None:
    return None if _status(status) is S.DRAFT else ErrorCode.INVALID_TRANSITION


def assign_error(status: str) -> ErrorCode | None:
    return None if _status(status) in (S.SUBMITTED, S.IN_REVIEW) else ErrorCode.INVALID_TRANSITION


def mark_reviewed_error(status: str) -> ErrorCode | None:
    return None if _status(status) is S.IN_REVIEW else ErrorCode.INVALID_TRANSITION


def approve_error(status: str, required_reviewer_role: str | None) -> ErrorCode | None:
    """`required_reviewer_role` is the routing for the draft as it stands: for a `draft` it is
    the routing the implicit submit would apply."""
    current = _status(status)
    if current is S.REVIEWED:
        return None
    if current in (S.SUBMITTED, S.DRAFT):
        return None if required_reviewer_role == APPROVER else ErrorCode.REVIEW_REQUIRED
    if current is S.IN_REVIEW:
        return ErrorCode.REVIEW_REQUIRED
    return ErrorCode.INVALID_TRANSITION


def request_changes_error(status: str) -> ErrorCode | None:
    return None if _status(status) in _PRE_DECISION else ErrorCode.INVALID_TRANSITION


def reject_error(status: str) -> ErrorCode | None:
    return None if _status(status) in _PRE_DECISION else ErrorCode.INVALID_TRANSITION


def publish_error(status: str, required_reviewer_role: str | None) -> ErrorCode | None:
    """Only approved content is published. Publishing something that still needs its required
    review is REVIEW_REQUIRED (it would skip that review); anything else is INVALID_TRANSITION."""
    current = _status(status)
    if current is S.APPROVED:
        return None
    if current is S.IN_REVIEW or (
        current in (S.DRAFT, S.SUBMITTED) and required_reviewer_role != APPROVER
    ):
        return ErrorCode.REVIEW_REQUIRED
    return ErrorCode.INVALID_TRANSITION


def implicit_submit(status: str) -> bool:
    """D4: a decision on a draft submits it first."""
    return _status(status) is S.DRAFT


def routed_status(required_reviewer_role: str | None) -> S:
    return S.SUBMITTED if required_reviewer_role == APPROVER else S.IN_REVIEW


def status_after_decision(action: str) -> S:
    return {
        "approved": S.APPROVED,
        "rejected": S.REJECTED,
        "changes_requested": S.NEEDS_CHANGES,
    }[action]
