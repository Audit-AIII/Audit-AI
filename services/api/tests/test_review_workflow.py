"""Phase 5: the review decision state machine, end to end through the API.

The rules are the existing ones (approval_rules.py, 00_CONTEXT.md "Governance invariants",
DECISIONS.md decision 1) - these tests pin them over every route, they add none:

1. a review is decided only from completed / needs_human_review: every decision on an already
   decided review (approved, changes_requested, rejected) is a 409 that changes nothing;
   -> test_a_decided_review_cannot_be_decided_again (parametrised: 3 x 3)
2. a failed or source_changed review can't be decided either way;
   -> test_failed_review_cannot_be_decided_any_way
   -> test_source_changed_review_cannot_be_decided_any_way
3. every request leaves a finished review (never draft / queued / analysing), on all three
   routes that start one;
   -> test_every_route_leaves_a_finished_review
4. a decision whose write fails part-way is rolled back whole: no approval event, no audit
   event, status unchanged - and the review can still be decided afterwards (no stuck lock);
   -> test_a_failed_decision_write_leaves_nothing_behind
5. after a decision, the way forward is a new version or a re-run, each a new decidable review;
   the decided review and its event stay as they were.
   -> test_after_a_decision_a_new_version_or_rerun_is_decidable_again
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import requires_db
from inkloom_api.models import ApprovalEvent, AuditEvent, Review

FINISHED = {"completed", "needs_human_review", "failed"}
DECISIONS = {
    "approved": ("approve", None),
    "changes_requested": ("request-changes", {"decision": "changes_requested", "note": "tighten the claim"}),
    "rejected": ("request-changes", {"decision": "rejected"}),
}


def _decide(client, account, content_version_id: str, decision: str):
    route, body = DECISIONS[decision]
    return client.post(f"/api/content-versions/{content_version_id}/{route}", json=body, headers=account.headers)


def _state(db_session, review_id: str) -> tuple[str, int, int]:
    """(review status, approval events on it, decision audit events on its version)."""
    db_session.expire_all()
    review = db_session.get(Review, uuid.UUID(review_id))
    events = db_session.query(ApprovalEvent).filter_by(review_id=review.id).count()
    audits = db_session.query(AuditEvent).filter(
        AuditEvent.entity_id == str(review.content_version_id),
        AuditEvent.event_type.in_([f"content_version.{d}" for d in DECISIONS]),
    ).count()
    return review.status, events, audits


@requires_db
@pytest.mark.parametrize("first", list(DECISIONS))
@pytest.mark.parametrize("second", list(DECISIONS))
def test_a_decided_review_cannot_be_decided_again(client, force_stub_mode, db_session, account_factory, first, second) -> None:
    owner = account_factory("owner")
    review = owner.submit()
    assert _decide(client, owner, review["content_version_id"], first).status_code == 201

    again = _decide(client, owner, review["content_version_id"], second)
    assert again.status_code == 409, again.text
    assert again.json()["error"] == {"code": "CONFLICT", "message": f"cannot decide a review in status '{first}'",
                                     "request_id": again.headers["X-Request-ID"]}
    assert _state(db_session, review["id"]) == (first, 1, 1)


@requires_db
def test_failed_review_cannot_be_decided_any_way(client, force_stub_mode, db_session, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    review = owner.submit()
    assert review["status"] == "failed"
    for decision in DECISIONS:
        response = _decide(client, owner, review["content_version_id"], decision)
        assert response.status_code == 409 and "'failed'" in response.json()["error"]["message"], decision
    assert _state(db_session, review["id"]) == ("failed", 0, 0)


@requires_db
def test_source_changed_review_cannot_be_decided_any_way(client, force_stub_mode, db_session, account_factory) -> None:
    owner = account_factory("owner")
    review = owner.submit()
    assert _decide(client, owner, review["content_version_id"], "approved").status_code == 201
    # Stub findings cite nothing, so flip the decided review the way a withdrawn cited source does.
    db_session.query(Review).filter_by(id=uuid.UUID(review["id"])).update({"status": "source_changed"})
    db_session.commit()
    for decision in DECISIONS:
        response = _decide(client, owner, review["content_version_id"], decision)
        assert response.status_code == 409 and "'source_changed'" in response.json()["error"]["message"], decision
    assert _state(db_session, review["id"]) == ("source_changed", 1, 1)


@requires_db
def test_every_route_leaves_a_finished_review(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner")
    created = owner.submit()
    rerun = client.post(f"/api/reviews/{created['id']}/rerun", headers=owner.headers).json()
    edited = client.post(f"/api/content/{created['content_item_id']}/versions",
                         json={"text": "Lumen Pods offer 12 hours."}, headers=owner.headers).json()["review"]
    for review in (created, rerun, edited):
        assert review["status"] in FINISHED, review["status"]
        assert review["started_at"] and review["completed_at"]
        stored = client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json()
        assert stored["status"] == review["status"]


@requires_db
@pytest.mark.parametrize("decision", list(DECISIONS))
def test_a_failed_decision_write_leaves_nothing_behind(force_stub_mode, db_session, account_factory, monkeypatch, decision) -> None:
    from inkloom_api.main import app
    from inkloom_api.routers import content_versions

    owner = account_factory("owner")
    review = owner.submit()
    before = _state(db_session, review["id"])
    real_record_decision = content_versions.record_decision

    def record_then_fail(*args, **kwargs):
        real_record_decision(*args, **kwargs)  # the event and status change are added...
        raise RuntimeError("database went away")  # ...then the request dies before commit

    monkeypatch.setattr(content_versions, "record_decision", record_then_fail)
    with TestClient(app, raise_server_exceptions=False) as safe_client:
        failed = _decide(safe_client, owner, review["content_version_id"], decision)
        assert failed.status_code == 500 and failed.json()["error"]["code"] == "INTERNAL_ERROR"
        assert _state(db_session, review["id"]) == before == ("needs_human_review", 0, 0)

        monkeypatch.setattr(content_versions, "record_decision", real_record_decision)
        assert _decide(safe_client, owner, review["content_version_id"], decision).status_code == 201
    assert _state(db_session, review["id"]) == (decision, 1, 1)


@requires_db
def test_after_a_decision_a_new_version_or_rerun_is_decidable_again(client, force_stub_mode, db_session, account_factory) -> None:
    owner = account_factory("owner")
    v1 = owner.submit()
    assert _decide(client, owner, v1["content_version_id"], "changes_requested").status_code == 201

    v2 = client.post(f"/api/content/{v1['content_item_id']}/versions",
                     json={"text": "Lumen Pods offer up to 12 hours."}, headers=owner.headers).json()
    assert v2["review"]["status"] == "needs_human_review"
    assert _decide(client, owner, v1["content_version_id"], "approved").status_code == 409  # v1 is stale now
    assert _decide(client, owner, str(v2["content_version_id"]), "rejected").status_code == 201

    rerun = client.post(f"/api/reviews/{v2['review']['id']}/rerun", headers=owner.headers).json()
    assert rerun["id"] != v2["review"]["id"] and rerun["status"] == "needs_human_review"
    assert _decide(client, owner, str(v2["content_version_id"]), "approved").status_code == 201

    assert _state(db_session, v1["id"]) == ("changes_requested", 1, 1)
    assert _state(db_session, v2["review"]["id"])[:2] == ("rejected", 1)
    assert _state(db_session, rerun["id"])[:2] == ("approved", 1)
