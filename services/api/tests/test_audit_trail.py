"""Round 3 Phase 5: the audit trail (docs/governance.md 9.3; contract example
contract/examples/governance_audit_history.json).

- every governance action writes its event, with actor, workspace, draft, version and note;
- GET /api/content/{id}/audit returns a draft's history newest first, paginated by cursor, with
  older (pre-Round 3) event types mapped to stable action names;
- GET /api/workspace/audit returns membership events, for owners only;
- audit_events refuses UPDATE at the database level (migration 0016).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from conftest import join_workspace, requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule
from inkloom_api.models import AuditEvent

pytestmark = requires_db

RULES = [
    ScriptedRule(
        "24 hours of playback",
        "CONTRADICTED",
        "up to 12 hours of playback per charge",
        "The fact sheet gives 12 hours.",
    ),
    ScriptedRule("playback per charge", "SUPPORTED", "up to 12 hours of playback per charge"),
]
RISKY = "Lumen Pods offer up to 24 hours of playback per charge."


@pytest.fixture
def team(client, monkeypatch, account_factory):
    use_scripted_provider(monkeypatch, RULES)
    owner = account_factory("owner")
    people = {"owner": owner}
    for role in ("writer", "reviewer", "approver"):
        people[role] = account_factory(role, with_source=False)
        join_workspace(client, owner, people[role], role)
    return people


def _post(client, actor, path, body=None):
    response = client.post(path, json=body, headers=actor.headers)
    return response


def _history(client, actor, item_id, **params):
    response = client.get(f"/api/content/{item_id}/audit", params=params, headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()


def _run_full_workflow(client, team) -> dict:
    """writer drafts a risky claim -> submit -> approve refused (review required) -> reviewer is
    assigned and sends it back -> writer edits -> resubmit -> reviewed -> approved -> published."""
    writer, reviewer, approver = team["writer"], team["reviewer"], team["approver"]
    draft = _post(
        client, writer, "/api/reviews", {"brand_id": team["owner"].brand_id, "text": RISKY}
    ).json()
    item = draft["content_item_id"]
    v1 = draft["content_version_id"]
    assert (
        _post(client, writer, f"/api/content/{item}/submit", {"content_version_id": v1}).status_code
        == 200
    )
    assert _post(client, approver, f"/api/content-versions/{v1}/approve").status_code == 409
    assert (
        _post(
            client, approver, f"/api/content/{item}/assign", {"reviewer_user_id": reviewer.user_id}
        ).status_code
        == 200
    )
    sent_back = _post(
        client,
        reviewer,
        f"/api/content-versions/{v1}/request-changes",
        {"decision": "changes_requested", "note": "The fact sheet says 12 hours."},
    )
    assert sent_back.status_code == 201, sent_back.text
    edited = _post(
        client,
        writer,
        f"/api/content/{item}/versions",
        {"text": "Lumen Pods offer up to 24 hours of playback per charge with the case."},
    ).json()
    v2 = str(edited["content_version_id"])
    assert (
        _post(client, writer, f"/api/content/{item}/submit", {"content_version_id": v2}).status_code
        == 200
    )
    reviewed = _post(
        client,
        reviewer,
        f"/api/content/{item}/mark-reviewed",
        {"content_version_id": v2, "note": "Case figure checked."},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert _post(client, approver, f"/api/content-versions/{v2}/approve").status_code == 201
    assert _post(client, approver, f"/api/content-versions/{v2}/publish").status_code == 200
    return {"item": item, "v1": v1, "v2": v2}


def test_every_workflow_action_is_in_the_drafts_history(client, team) -> None:
    ids = _run_full_workflow(client, team)
    history = _history(client, team["writer"], ids["item"], limit=100)
    items = history["items"]
    assert history["next_cursor"] is None
    times = [i["created_at"] for i in items]
    assert times == sorted(times, reverse=True)  # newest first

    actions = [i["action"] for i in reversed(items)]  # oldest first, for reading
    expected_in_order = [
        "draft_created",
        "draft_submitted",
        "routing_decision",
        "review_requested",
        "approval_denied",
        "reviewer_assigned",
        "changes_requested",
        "version_created",
        "draft_submitted",
        "routing_decision",
        "review_requested",
        "reviewed",
        "approval_granted",
        "published",
    ]
    it = iter(actions)
    assert all(a in it for a in expected_in_order), actions  # in this order (others may be between)

    by_action = {}
    for entry in items:
        by_action.setdefault(entry["action"], entry)
    names = {p: team[p].user_id for p in ("writer", "reviewer", "approver")}
    assert by_action["published"]["actor"]["id"] == names["approver"]
    assert by_action["published"]["version_number"] == 2
    assert by_action["published"]["details"]["before"] == {"workflow_status": "approved"}
    assert by_action["approval_granted"]["event_type"] == "content_version.approved"
    assert by_action["reviewed"]["note"] == "Case figure checked."
    assert by_action["reviewed"]["actor"]["id"] == names["reviewer"]
    assert by_action["changes_requested"]["note"] == "The fact sheet says 12 hours."
    assert by_action["changes_requested"]["version_number"] == 1
    assert by_action["approval_denied"]["details"]["code"] == "REVIEW_REQUIRED"
    assert by_action["routing_decision"]["details"]["risk_level"] == "high"
    assert by_action["draft_created"]["version_number"] == 1
    assert all(
        e["actor"] is None or set(e["actor"]) == {"id", "display_name"} for e in items
    )  # never an email


def test_history_pages_newest_first_without_gaps_or_repeats(client, team) -> None:
    ids = _run_full_workflow(client, team)
    full = [i["id"] for i in _history(client, team["owner"], ids["item"], limit=100)["items"]]
    paged, cursor = [], None
    while True:
        page = _history(
            client, team["owner"], ids["item"], limit=3, **({"cursor": cursor} if cursor else {})
        )
        assert len(page["items"]) <= 3
        paged += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert paged == full
    bad = client.get(
        f"/api/content/{ids['item']}/audit",
        params={"cursor": "nonsense"},
        headers=team["owner"].headers,
    )
    assert bad.status_code == 422


def test_history_is_scoped_to_the_workspace(client, team, account_factory) -> None:
    ids = _run_full_workflow(client, team)
    outsider = account_factory("outsider", with_source=False)
    response = client.get(f"/api/content/{ids['item']}/audit", headers=outsider.headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_membership_events_are_in_the_workspace_log_for_owners_only(client, team) -> None:
    owner = team["owner"]
    pending = _post(
        client,
        owner,
        "/api/workspace/invitations",
        {"email": "later@example.com", "role": "writer"},
    ).json()
    assert (
        _post(
            client, owner, f"/api/workspace/invitations/{pending['invitation']['id']}/revoke"
        ).status_code
        == 200
    )
    changed = client.patch(
        f"/api/workspace/members/{team['writer'].user_id}",
        json={"role": "reviewer"},
        headers=owner.headers,
    )
    assert changed.status_code == 200
    assert (
        client.delete(
            f"/api/workspace/members/{team['writer'].user_id}", headers=owner.headers
        ).status_code
        == 200
    )

    log = client.get("/api/workspace/audit", params={"limit": 100}, headers=owner.headers)
    assert log.status_code == 200, log.text
    actions = [i["action"] for i in log.json()["items"]]
    for name in (
        "invite_created",
        "invite_accepted",
        "invite_revoked",
        "member_role_changed",
        "member_removed",
    ):
        assert name in actions, (name, actions)
    role_change = next(i for i in log.json()["items"] if i["action"] == "member_role_changed")
    assert role_change["details"]["before"] == {"role": "writer"}
    assert role_change["details"]["after"] == {"role": "reviewer"}
    assert role_change["actor"]["id"] == owner.user_id

    refused = client.get("/api/workspace/audit", headers=team["approver"].headers)
    assert refused.status_code == 403


def test_older_drafts_show_their_history_with_mapped_action_names(client, team, db_session) -> None:
    """A draft whose events were written before Round 3 (no content_item_id on them)."""
    draft = _post(
        client, team["writer"], "/api/reviews", {"brand_id": team["owner"].brand_id, "text": RISKY}
    ).json()
    db_session.query(AuditEvent).filter_by(
        content_item_id=uuid.UUID(draft["content_item_id"])
    ).delete()
    db_session.commit()
    legacy = AuditEvent(
        organisation_id=uuid.UUID(team["owner"].organisation_id),
        actor_user_id=uuid.UUID(team["owner"].user_id),
        event_type="content_version.rejected",
        entity_type="content_version",
        entity_id=draft["content_version_id"],
        details={"review_id": draft["id"], "note": "Old decision."},
    )
    db_session.add(legacy)
    db_session.commit()

    items = _history(client, team["owner"], draft["content_item_id"])["items"]
    by_type = {i["event_type"]: i for i in items}
    assert by_type["content_version.rejected"]["action"] == "approval_rejected"
    assert by_type["content_version.rejected"]["note"] == "Old decision."
    assert by_type["content_version.rejected"]["version_number"] == 1
    assert by_type["review.submitted"]["action"] == "draft_created"


def test_audit_events_are_append_only(client, team, db_session) -> None:
    event_id = (
        db_session.query(AuditEvent.id)
        .filter_by(organisation_id=uuid.UUID(team["owner"].organisation_id))
        .first()[0]
    )
    with pytest.raises(DBAPIError) as refused:
        db_session.execute(
            text("UPDATE audit_events SET event_type = 'tampered' WHERE id = :id"), {"id": event_id}
        )
    assert "append-only" in str(refused.value)
    db_session.rollback()
