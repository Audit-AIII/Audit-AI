"""Round 3 Phase 3: an author cannot approve their own content (docs/governance.md, decision D1).

- In a team (someone else could approve), the draft's author - and whoever wrote the version
  being approved - is refused with 403 SELF_APPROVAL_FORBIDDEN, owners included. Nothing changes
  except one `approval_denied` audit event.
- Alone (nobody else could approve), the author may sign off their own work; it is recorded as a
  self-approval and the review says `approval_mode: "self"`.
"""

from __future__ import annotations

import uuid

from conftest import join_workspace, requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule
from inkloom_api.models import ApprovalEvent, AuditEvent, Review

pytestmark = requires_db

# Clean drafts (every claim supported, nothing flagged) are routed to an approver only, so the
# self-approval rule is the only thing these tests exercise. Routing has its own tests.
SUPPORTED = [
    ScriptedRule("playback per charge", "SUPPORTED", "up to 12 hours of playback per charge")
]
CLEAN = "Lumen Pods offer up to 12 hours of playback per charge."


def _approve(client, actor, review: dict):
    return client.post(
        f"/api/content-versions/{review['content_version_id']}/approve", headers=actor.headers
    )


def _view(client, actor, review: dict) -> dict:
    return client.get(f"/api/reviews/{review['id']}", headers=actor.headers).json()


def _assert_unchanged_and_denied(db_session, review: dict, organisation_id: str) -> None:
    db_session.expire_all()
    row = db_session.get(Review, uuid.UUID(review["id"]))
    assert row.status == review["status"]
    assert db_session.query(ApprovalEvent).filter_by(review_id=row.id).count() == 0
    denied = (
        db_session.query(AuditEvent)
        .filter_by(organisation_id=uuid.UUID(organisation_id), event_type="approval_denied")
        .filter(AuditEvent.entity_id == review["content_version_id"])
        .all()
    )
    assert len(denied) == 1
    assert denied[0].details["code"] == "SELF_APPROVAL_FORBIDDEN"
    assert denied[0].details["reason"] == "author cannot approve their own content"


def test_owner_cannot_approve_own_draft_when_an_approver_exists(
    client, monkeypatch, account_factory, db_session
) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("owner")
    approver = account_factory("approver", with_source=False)
    join_workspace(client, owner, approver, "approver")
    review = owner.submit(CLEAN)

    seen = _view(client, owner, review)
    assert seen["approval_mode"] == "team"
    assert "approve" not in seen["allowed_actions"]
    assert "approve" in _view(client, approver, review)["allowed_actions"]

    refused = _approve(client, owner, review)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "SELF_APPROVAL_FORBIDDEN"
    _assert_unchanged_and_denied(db_session, review, owner.organisation_id)

    approved = _approve(client, approver, review)
    assert approved.status_code == 201, approved.text


def test_approver_who_wrote_the_draft_cannot_approve_it(
    client, monkeypatch, account_factory, db_session
) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("owner")
    approver = account_factory("approver", with_source=False)
    join_workspace(client, owner, approver, "approver")
    # An approver can't create drafts today; an older draft of theirs (e.g. written while they
    # were a writer) is the realistic case. Make them its author directly.
    review = owner.submit(CLEAN)
    from inkloom_api.models import ContentItem, ContentVersion

    version = db_session.get(ContentVersion, uuid.UUID(review["content_version_id"]))
    item = db_session.get(ContentItem, version.content_item_id)
    item.created_by = version.created_by = uuid.UUID(approver.user_id)
    db_session.commit()

    refused = _approve(client, approver, review)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "SELF_APPROVAL_FORBIDDEN"
    _assert_unchanged_and_denied(db_session, review, owner.organisation_id)
    assert _approve(client, owner, review).status_code == 201


def test_owner_who_edited_a_writers_draft_cannot_approve_that_version(
    client, monkeypatch, account_factory
) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("owner")
    writer = account_factory("writer", with_source=False)
    approver = account_factory("approver", with_source=False)
    join_workspace(client, owner, writer, "writer")
    join_workspace(client, owner, approver, "approver")
    draft = writer.submit(CLEAN, brand_id=owner.brand_id)

    edited = client.post(
        f"/api/content/{draft['content_item_id']}/versions",
        json={"text": "Lumen Pods really offer up to 12 hours of playback per charge."},
        headers=owner.headers,
    )
    assert edited.status_code == 201, edited.text
    new_review = edited.json()["review"]
    assert "approve" not in new_review["allowed_actions"]
    refused = _approve(client, owner, new_review)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "SELF_APPROVAL_FORBIDDEN"
    assert _approve(client, approver, new_review).status_code == 201


def test_solo_owner_signs_off_own_work_as_a_labelled_self_approval(
    client, monkeypatch, account_factory, db_session
) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("solo")
    review = owner.submit(CLEAN)
    seen = _view(client, owner, review)
    assert seen["approval_mode"] == "self"
    assert "approve" in seen["allowed_actions"]

    approved = _approve(client, owner, review)
    assert approved.status_code == 201, approved.text
    db_session.expire_all()
    event = (
        db_session.query(AuditEvent)
        .filter_by(event_type="content_version.approved", entity_id=review["content_version_id"])
        .one()
    )
    assert event.details["self_approval"] is True
    assert event.details["reason"] == "sole_member"


def test_reviewers_and_writers_do_not_count_as_someone_else_who_could_approve(
    client, monkeypatch, account_factory
) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("owner")
    reviewer = account_factory("reviewer", with_source=False)
    join_workspace(client, owner, reviewer, "reviewer")
    review = owner.submit(CLEAN)
    assert _view(client, owner, review)["approval_mode"] == "self"
    assert _approve(client, owner, review).status_code == 201


def test_rule_follows_membership_changes(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("owner")
    approver = account_factory("approver", with_source=False)
    first = owner.submit(CLEAN)
    second = owner.submit("Lumen Pods give up to 12 hours of playback per charge.")

    join_workspace(client, owner, approver, "approver")
    assert _approve(client, owner, first).status_code == 403

    removed = client.delete(f"/api/workspace/members/{approver.user_id}", headers=owner.headers)
    assert removed.status_code == 200
    assert _approve(client, owner, second).status_code == 201  # alone again: solo sign-off
