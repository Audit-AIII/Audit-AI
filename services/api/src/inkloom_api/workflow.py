"""The draft workflow, where the state machine (workflow_rules.py) and the routing rule
(risk_policy.py) meet the database (Round 3 Phase 4, docs/governance.md sections 6-7).

Every function here runs inside the caller's transaction and writes its audit events there, so a
state change and its record commit together. A refusal raises before anything is written -
except `deny`, which records one `approval_denied` event and nothing else.

Hooks the rest of the backend calls:
- `on_review_finished`: after any AI check of a draft (create, upload, rerun, new version) -
  stores the routing decision, and re-routes a submitted draft whose findings changed;
- `on_new_version`: a new version always starts again from `draft`;
- `on_source_changed`: a cited source changed under an approved draft - it is `blocked`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.orm import Session

from . import workflow_rules
from .approval_rules import DECIDABLE_STATES
from .approval_service import (
    SelfApprovalForbiddenError,
    check_not_self_approval,
    other_approver_exists,
    other_member_can,
)
from .audit import log_audit_event
from .auth.dependencies import AuthContext
from .auth.permissions import Permission, can, is_author
from .config import get_settings
from .errors import ApiException, ErrorCode
from .models import ContentItem, ContentVersion, Membership, Review
from .risk_policy import RiskAssessment, assess, risk_rank
from .statuses import WorkflowStatus as S

_MESSAGES = {
    ErrorCode.REVIEW_REQUIRED: "this draft needs a reviewer's check before it can be {verb}",
    ErrorCode.INVALID_TRANSITION: "cannot {action} content in status '{status}'",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _status(item: ContentItem, new: S) -> None:
    item.workflow_status = new.value
    item.workflow_updated_at = _now()


def _log(
    db: Session,
    item: ContentItem,
    event_type: str,
    actor_user_id: uuid.UUID | None,
    version_number: int | None,
    details: dict | None = None,
    note: str | None = None,
) -> None:
    log_audit_event(
        db,
        organisation_id=item.organisation_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        entity_type="content_item",
        entity_id=item.id,
        details=details,
        content_item_id=item.id,
        version_number=version_number,
        note=note,
    )


def _move(details: dict | None, before: str, after: str) -> dict:
    return {
        **(details or {}),
        "before": {"workflow_status": before},
        "after": {"workflow_status": after},
    }


def _refuse(code: ErrorCode, message: str) -> ApiException:
    http = (
        status.HTTP_403_FORBIDDEN if code.name.endswith("FORBIDDEN") else status.HTTP_409_CONFLICT
    )
    return ApiException(http, code, message)


def _transition_error(code: ErrorCode, action: str, item: ContentItem) -> ApiException:
    if code is ErrorCode.REVIEW_REQUIRED:
        verb = "published" if action == "publish" else "approved"
        return _refuse(code, item.routing_reason_text or _MESSAGES[code].format(verb=verb))
    return _refuse(code, _MESSAGES[code].format(action=action, status=item.workflow_status))


def _ensure_current(version: ContentVersion) -> None:
    if not version.is_current:
        raise _refuse(
            ErrorCode.CONFLICT, "a newer version of this content exists; this review is stale"
        )


def latest_review(db: Session, content_version_id: uuid.UUID, lock: bool = False) -> Review | None:
    query = (
        db.query(Review)
        .filter_by(content_version_id=content_version_id)
        .order_by(Review.created_at.desc(), Review.id.desc())
    )
    return (query.with_for_update() if lock else query).first()


def current_version(db: Session, item: ContentItem) -> ContentVersion:
    return db.query(ContentVersion).filter_by(content_item_id=item.id, is_current=True).one()


def lock_item(db: Session, item_id: uuid.UUID) -> ContentItem:
    """Re-reads the draft with a row lock, so two workflow actions on it serialize."""
    return db.query(ContentItem).filter_by(id=item_id).with_for_update().one()


def deny(
    db: Session,
    auth: AuthContext,
    item_id: uuid.UUID,
    version: ContentVersion,
    error: ApiException,
    attempted: str,
) -> None:
    """Refuses an approve/publish: rolls back everything this request started (and its locks),
    then records one `approval_denied` event in its own commit, then raises. The draft itself
    never changes on a refusal."""
    db.rollback()
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="approval_denied",
        entity_type="content_version",
        entity_id=version.id,
        details={
            "code": error.code.value,
            "reason": SELF_APPROVAL_MESSAGE
            if error.code is ErrorCode.SELF_APPROVAL_FORBIDDEN
            else error.detail,
            "attempted": attempted,
            "content_item_id": str(item_id),
            "version_number": version.version_number,
        },
        content_item_id=item_id,
        version_number=version.version_number,
        note=error.detail,
    )
    db.commit()
    raise error


SELF_APPROVAL_MESSAGE = "author cannot approve their own content"


def self_approval_error() -> ApiException:
    return _refuse(
        ErrorCode.SELF_APPROVAL_FORBIDDEN, "you wrote this draft, so someone else has to approve it"
    )


# --- Routing ------------------------------------------------------------------------------------


def effective_assessment(item: ContentItem, review: Review) -> RiskAssessment | None:
    """The routing for this review of the draft: computed fresh (same `assess`) when the stored
    routing belongs to an older check - drafts from before Round 3, for instance."""
    if item.routed_review_id == review.id and item.required_reviewer_role:
        return None  # the stored routing is for this review: use it
    return assess(review, list(review.findings))


def apply_assessment(item: ContentItem, review: Review, assessment: RiskAssessment) -> None:
    item.risk_level = assessment.level
    item.required_reviewer_role = assessment.required_reviewer_role
    item.routing_reason_code = assessment.reason_code
    item.routing_reason_text = assessment.reason_text
    item.routing_details = {
        "review_id": str(review.id),
        "triggered_by": [t.as_dict() for t in assessment.triggers],
    }
    item.routed_review_id = review.id


def _routing_details(assessment: RiskAssessment, review: Review) -> dict:
    return {
        "risk_level": assessment.level,
        "required_reviewer_role": assessment.required_reviewer_role,
        "reason_code": assessment.reason_code,
        "review_id": str(review.id),
        "finding_ids": [t.finding_id for t in assessment.triggers],
        "codes": sorted({t.code for t in assessment.triggers}),
    }


def on_review_finished(
    db: Session, item: ContentItem, review: Review, actor_user_id: uuid.UUID | None
) -> None:
    """Stores the routing for the draft's newest check and, if the draft was already submitted,
    re-routes it when the findings now need a reviewer they didn't before.

    A decision (approved, rejected, needs changes) belonged to the check it was made on, so a new
    finished check of the same version opens the draft again as `draft` (the old decision stays
    in the history, like an approval of an older version). A failed re-check leaves a decision
    standing, and published content stays published."""
    version = db.get(ContentVersion, review.content_version_id)
    if version is None or not version.is_current:
        return  # a re-check of an older version changes nothing about the draft
    db.flush()
    db.refresh(review)
    assessment = assess(review, list(review.findings))
    if assessment is None:
        return
    before = item.workflow_status
    decided = before in (S.APPROVED, S.REJECTED, S.NEEDS_CHANGES)
    if before == S.PUBLISHED.value:
        if not assessment.blocked:
            apply_assessment(item, review, assessment)
        return

    if assessment.blocked:
        if decided:
            return
        apply_assessment(item, review, assessment)
        _status(item, S.BLOCKED)
        if before != S.BLOCKED.value:
            _log(
                db,
                item,
                "routing_decision",
                actor_user_id,
                version.version_number,
                _move(_routing_details(assessment, review), before, S.BLOCKED.value),
                note=assessment.reason_text,
            )
        return

    previous_rank = risk_rank(item.risk_level) if item.risk_level else None
    apply_assessment(item, review, assessment)
    after = before
    if before == S.BLOCKED.value or decided:
        after = S.DRAFT.value
    elif assessment.needs_reviewer and (
        before == S.SUBMITTED.value
        or (
            before == S.REVIEWED.value
            and (previous_rank is None or risk_rank(assessment.level) > previous_rank)
        )
    ):
        after = S.IN_REVIEW.value  # the findings changed after submission: a reviewer again
    if after != before:
        _status(item, S(after))
    if after != before or before in (S.SUBMITTED, S.IN_REVIEW, S.REVIEWED):
        _log(
            db,
            item,
            "routing_decision",
            actor_user_id,
            version.version_number,
            _move({**_routing_details(assessment, review), "rerouted": True}, before, after),
            note=assessment.reason_text,
        )


def on_new_version(item: ContentItem) -> None:
    """Any edit starts the workflow again: the old version's review and approval are history."""
    _status(item, S.DRAFT)
    item.reviewed_by = None
    item.reviewed_at = None


def on_source_changed(
    db: Session,
    content_version_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    reason: str,
) -> None:
    version = db.get(ContentVersion, content_version_id)
    if version is None or not version.is_current:
        return
    item = db.get(ContentItem, version.content_item_id)
    before = item.workflow_status
    if before == S.BLOCKED.value:
        return
    _status(item, S.BLOCKED)
    item.routing_reason_code = "source_changed"
    item.routing_reason_text = "A source this check cited has changed since. Re-check the draft."
    _log(
        db,
        item,
        "routing_decision",
        actor_user_id,
        version.version_number,
        _move({"reason_code": "source_changed", "reason": reason}, before, S.BLOCKED.value),
        note=item.routing_reason_text,
    )


# --- Actions ------------------------------------------------------------------------------------


def submit(
    db: Session,
    auth: AuthContext,
    item: ContentItem,
    version: ContentVersion,
    review: Review,
    *,
    implicit: bool = False,
) -> RiskAssessment:
    """draft -> in_review (a reviewer is needed) or submitted (clean: approver only). With
    `implicit`, called by a decision on a draft (D4), after that route's own checks."""
    _ensure_current(version)
    code = workflow_rules.submit_error(item.workflow_status)
    if code:
        raise _transition_error(code, "submit", item)
    if review.status not in DECIDABLE_STATES:
        raise _refuse(
            ErrorCode.INVALID_TRANSITION,
            f"the AI check of this version is '{review.status}'; it must finish before submitting",
        )
    assessment = assess(review, list(review.findings))
    apply_assessment(item, review, assessment)
    before = item.workflow_status
    after = workflow_rules.routed_status(assessment.required_reviewer_role)
    item.submitted_by = auth.user_id
    item.submitted_at = _now()
    _status(item, after)
    details = _routing_details(assessment, review)
    _log(
        db,
        item,
        "draft_submitted",
        auth.user_id,
        version.version_number,
        _move({"implicit": implicit}, before, after.value),
    )
    _log(
        db,
        item,
        "routing_decision",
        auth.user_id,
        version.version_number,
        details,
        note=assessment.reason_text,
    )
    if after is S.IN_REVIEW:
        _log(
            db,
            item,
            "review_requested",
            auth.user_id,
            version.version_number,
            {"required_reviewer_role": assessment.required_reviewer_role},
            note=assessment.reason_text,
        )
    return assessment


def assign(
    db: Session, auth: AuthContext, item: ContentItem, reviewer_user_id: uuid.UUID | None
) -> None:
    """Sets (or with None clears) the draft's assigned reviewer. A reviewer may only take a
    draft themself; approvers and owners may assign anyone who can review it. Never the
    draft's author (D6)."""
    auth.require(Permission.ASSIGN)
    code = workflow_rules.assign_error(item.workflow_status)
    if code:
        raise _transition_error(code, "assign a reviewer to", item)
    acting_as_reviewer_only = not can(auth.role, auth.user_id, Permission.APPROVE)
    if acting_as_reviewer_only and reviewer_user_id not in (auth.user_id, None):
        raise _refuse(ErrorCode.FORBIDDEN, "a reviewer can only assign a draft to themself")
    if (
        acting_as_reviewer_only
        and reviewer_user_id is None
        and item.assigned_reviewer_id
        not in (
            None,
            auth.user_id,
        )
    ):
        raise _refuse(ErrorCode.FORBIDDEN, "a reviewer can only unassign themself")
    if reviewer_user_id is not None:
        member = (
            db.query(Membership)
            .filter_by(
                organisation_id=auth.organisation_id, user_id=reviewer_user_id, is_active=True
            )
            .one_or_none()
        )
        if member is None or not can(member.role, reviewer_user_id, Permission.MARK_REVIEWED):
            raise ApiException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ErrorCode.VALIDATION_ERROR,
                "the assignee must be a member of this workspace who can review drafts",
            )
        if reviewer_user_id == item.created_by:
            raise ApiException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ErrorCode.VALIDATION_ERROR,
                "a draft can't be assigned to its own author for review",
            )
    before = item.assigned_reviewer_id
    item.assigned_reviewer_id = reviewer_user_id
    version = current_version(db, item)
    _log(
        db,
        item,
        "reviewer_assigned",
        auth.user_id,
        version.version_number,
        {
            "before": {"assigned_reviewer_id": str(before) if before else None},
            "after": {"assigned_reviewer_id": str(reviewer_user_id) if reviewer_user_id else None},
        },
    )


def mark_reviewed(
    db: Session,
    auth: AuthContext,
    item: ContentItem,
    version: ContentVersion,
    review: Review,
    note: str | None,
) -> None:
    auth.require(Permission.MARK_REVIEWED)
    _ensure_current(version)
    code = workflow_rules.mark_reviewed_error(item.workflow_status)
    if code:
        raise _transition_error(code, "mark reviewed", item)
    if review.status not in DECIDABLE_STATES:
        raise _refuse(
            ErrorCode.INVALID_TRANSITION, f"the AI check of this version is '{review.status}'"
        )
    if is_author(auth.user_id, item, version) and other_member_can(
        db, auth.organisation_id, auth.user_id, Permission.MARK_REVIEWED
    ):
        raise _refuse(
            ErrorCode.SELF_REVIEW_FORBIDDEN,
            "you wrote this draft, so someone else has to review it",
        )
    before = item.workflow_status
    item.reviewed_by = auth.user_id
    item.reviewed_at = _now()
    _status(item, S.REVIEWED)
    _log(
        db,
        item,
        "reviewed",
        auth.user_id,
        version.version_number,
        _move(
            {"review_id": str(review.id), "risk_level": item.risk_level}, before, S.REVIEWED.value
        ),
        note=note,
    )


@dataclass(frozen=True)
class DecisionPlan:
    implicit_submit: bool  # D4: the decision submits the draft first
    solo_review: bool  # P4: the approval also stands in for the review (solo workspace)


def is_solo_reviewer(db: Session, auth: AuthContext) -> bool:
    """The caller could review and approve, and nobody else in the workspace could do either
    (DECISIONS_PENDING.md P4, setting `solo_review_shortcut`)."""
    return (
        get_settings().solo_review_shortcut
        and can(auth.role, auth.user_id, Permission.MARK_REVIEWED)
        and can(auth.role, auth.user_id, Permission.APPROVE)
        and not other_member_can(db, auth.organisation_id, auth.user_id, Permission.MARK_REVIEWED)
        and not other_approver_exists(db, auth.organisation_id, auth.user_id)
    )


def solo_review(
    db: Session, auth: AuthContext, item: ContentItem, version: ContentVersion, review: Review
) -> None:
    """Records the review a solo approver's approval stands in for (P4)."""
    if item.workflow_status != S.IN_REVIEW.value:
        return
    before = item.workflow_status
    item.reviewed_by = auth.user_id
    item.reviewed_at = _now()
    _status(item, S.REVIEWED)
    _log(
        db,
        item,
        "reviewed",
        auth.user_id,
        version.version_number,
        _move(
            {
                "review_id": str(review.id),
                "risk_level": item.risk_level,
                "self_review": True,
                "reason": "sole_member",
            },
            before,
            S.REVIEWED.value,
        ),
    )


def check_decision(
    db: Session,
    auth: AuthContext,
    item: ContentItem,
    version: ContentVersion,
    review: Review,
    action: str,
) -> DecisionPlan:
    """The workflow half of approve / send back / reject: raises when the draft's state doesn't
    allow the decision; otherwise says whether it submits the draft first (D4) and whether a solo
    approval also stands in for the review (P4)."""
    _ensure_current(version)
    current = item.workflow_status
    if action == "approved":
        fresh = effective_assessment(item, review) if current == S.DRAFT.value else None
        if fresh is not None and not fresh.blocked:
            apply_assessment(item, review, fresh)  # so a refusal message can say why
        routing = item.required_reviewer_role
        code = workflow_rules.approve_error(current, routing)
        if code is ErrorCode.REVIEW_REQUIRED and is_solo_reviewer(db, auth):
            return DecisionPlan(workflow_rules.implicit_submit(current), solo_review=True)
        if code:
            raise _transition_error(code, "approve", item)
        if (
            current == S.REVIEWED.value
            and item.reviewed_by == auth.user_id
            and other_approver_exists(db, auth.organisation_id, auth.user_id)
        ):
            raise _refuse(
                ErrorCode.SAME_REVIEWER_APPROVER_FORBIDDEN,
                "you reviewed this version, so a different person has to approve it",
            )
    elif action == "changes_requested":
        code = workflow_rules.request_changes_error(current)
        if code:
            raise _transition_error(code, "send back", item)
    else:
        code = workflow_rules.reject_error(current)
        if code:
            raise _transition_error(code, "reject", item)
    return DecisionPlan(workflow_rules.implicit_submit(current), solo_review=False)


def finish_decision(item: ContentItem, action: str) -> S:
    after = workflow_rules.status_after_decision(action)
    _status(item, after)
    return after


def publish(
    db: Session,
    auth: AuthContext,
    item: ContentItem,
    version: ContentVersion,
) -> None:
    """approved -> published. Same self-approval rule as approve: the author doesn't publish
    their own work unless nobody else could (D1). Refusals are recorded by the route (`deny`)."""
    auth.require(Permission.PUBLISH)
    _ensure_current(version)
    code = workflow_rules.publish_error(item.workflow_status, item.required_reviewer_role)
    if code:
        raise _transition_error(code, "publish", item)
    try:
        self_approval = check_not_self_approval(
            db, auth.organisation_id, auth.user_id, item, version
        )
    except SelfApprovalForbiddenError:
        raise self_approval_error() from None
    before = item.workflow_status
    _status(item, S.PUBLISHED)
    _log(
        db,
        item,
        "published",
        auth.user_id,
        version.version_number,
        _move(
            {"self_approval": True, "reason": "sole_member"} if self_approval else None,
            before,
            S.PUBLISHED.value,
        ),
    )
