"""Round 3 Phase 6: the whole governance workflow end to end, with separate real users.

A team workspace - owner, writer, reviewer, approver - and an outsider with a workspace of their
own. A writer's draft with a contradicted claim goes draft -> in_review -> reviewed -> approved ->
published. At every state, for every person:

- `allowed_actions` is exactly the documented set (docs/governance.md 9.2);
- every workflow action NOT in that set is attempted through its real route and refused (403 /
  409 / 422), and the draft's state is unchanged afterwards - so the list never offers less or
  more than the server permits.

Also: the solo flow everybody starts with (sign up -> brand document -> check -> approve ->
publish) still works, and the author can't publish their own work in a team.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import join_workspace, requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule
from inkloom_api.models import AuditEvent, ContentItem

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
CLEAN = "Lumen Pods offer up to 12 hours of playback per charge."

WORKFLOW_ACTIONS = (
    "submit",
    "assign",
    "mark_reviewed",
    "approve",
    "request_changes",
    "reject",
    "publish",
    "create_version",
    "rerun",
)
_ALWAYS = {"comment"}  # every member may comment; checked separately

# Expected allowed_actions on the writer's risky draft, per state and person.
EXPECTED = {
    "draft": {
        "owner": {
            "create_version",
            "rerun",
            "submit",
            "request_changes",
            "reject",
            "dismiss_finding",
        },
        "approver": {"rerun", "request_changes", "reject", "dismiss_finding"},
        "reviewer": {"rerun", "request_changes", "dismiss_finding"},
        "writer": {"create_version", "rerun", "submit"},
    },
    "in_review": {
        "owner": {
            "create_version",
            "rerun",
            "assign",
            "mark_reviewed",
            "request_changes",
            "reject",
            "dismiss_finding",
        },
        "approver": {"rerun", "assign", "request_changes", "reject", "dismiss_finding"},
        "reviewer": {"rerun", "assign", "mark_reviewed", "request_changes", "dismiss_finding"},
        "writer": {"create_version", "rerun"},
    },
    "reviewed": {
        "owner": {
            "create_version",
            "rerun",
            "approve",
            "request_changes",
            "reject",
            "dismiss_finding",
        },
        "approver": {"rerun", "approve", "request_changes", "reject", "dismiss_finding"},
        "reviewer": {"rerun", "request_changes", "dismiss_finding"},
        "writer": {"create_version", "rerun"},
    },
    "approved": {
        "owner": {"create_version", "rerun", "publish", "dismiss_finding"},
        "approver": {"rerun", "publish", "dismiss_finding"},
        "reviewer": {"rerun", "dismiss_finding"},
        "writer": {"create_version", "rerun"},
    },
    "published": {
        "owner": {"create_version", "rerun", "dismiss_finding"},
        "approver": {"rerun", "dismiss_finding"},
        "reviewer": {"rerun", "dismiss_finding"},
        "writer": {"create_version", "rerun"},
    },
}


@pytest.fixture
def team(client, monkeypatch, account_factory):
    use_scripted_provider(monkeypatch, RULES)
    people = {"owner": account_factory("owner")}
    for role in ("writer", "reviewer", "approver"):
        people[role] = account_factory(role, with_source=False)
        join_workspace(client, people["owner"], people[role], role)
    people["outsider"] = account_factory("outsider")
    return people


def _call(client, actor, action, review, reviewer_id=None):
    item, cv = review["content_item_id"], review["content_version_id"]
    calls = {
        "submit": ("post", f"/api/content/{item}/submit", {"content_version_id": cv}),
        "assign": ("post", f"/api/content/{item}/assign", {"reviewer_user_id": reviewer_id}),
        "mark_reviewed": ("post", f"/api/content/{item}/mark-reviewed", {"content_version_id": cv}),
        "approve": ("post", f"/api/content-versions/{cv}/approve", None),
        "request_changes": (
            "post",
            f"/api/content-versions/{cv}/request-changes",
            {"decision": "changes_requested"},
        ),
        "reject": ("post", f"/api/content-versions/{cv}/request-changes", {"decision": "rejected"}),
        "publish": ("post", f"/api/content-versions/{cv}/publish", None),
        "create_version": ("post", f"/api/content/{item}/versions", {"text": CLEAN}),
        "rerun": ("post", f"/api/reviews/{review['id']}/rerun", None),
        "comment": (
            "post",
            f"/api/findings/{review['findings'][0]['finding_id']}/comments",
            {"body": "Noted."},
        ),
        "audit": ("get", f"/api/content/{item}/audit", None),
        "view": ("get", f"/api/reviews/{review['id']}", None),
    }
    method, path, body = calls[action]
    if method == "get":
        return client.get(path, headers=actor.headers)
    return client.post(path, json=body, headers=actor.headers)


def _status(db_session, review) -> str:
    db_session.expire_all()
    return db_session.get(ContentItem, uuid.UUID(review["content_item_id"])).workflow_status


def _check_state(client, db_session, team, review, state: str) -> None:
    assert _status(db_session, review) == state
    reviewer_id = team["reviewer"].user_id
    for person, expected in EXPECTED[state].items():
        actor = team[person]
        seen = _call(client, actor, "view", review).json()
        assert seen["workflow_status"] == state
        assert set(seen["allowed_actions"]) - _ALWAYS == expected, (state, person)
        assert "comment" in seen["allowed_actions"]
        for action in WORKFLOW_ACTIONS:
            if action in expected:
                continue
            refused = _call(client, actor, action, seen, reviewer_id)
            assert refused.status_code in (403, 409, 422), (state, person, action, refused.text)
            assert _status(db_session, review) == state, (state, person, action)


def test_full_team_workflow_with_separate_users(client, db_session, team) -> None:
    writer, reviewer, approver = team["writer"], team["reviewer"], team["approver"]
    created = client.post(
        "/api/reviews",
        json={"brand_id": team["owner"].brand_id, "text": RISKY},
        headers=writer.headers,
    )
    assert created.status_code == 201, created.text
    review = created.json()
    assert (review["risk_level"], review["required_reviewer_role"]) == ("high", "reviewer")
    assert review["summary_counts"]["contradicted"] == 1
    assert review["author"]["id"] == writer.user_id and review["assigned_reviewer"] is None

    _check_state(client, db_session, team, review, "draft")
    assert _call(client, writer, "submit", review).status_code == 200

    _check_state(client, db_session, team, review, "in_review")
    assigned = _call(client, approver, "assign", review, reviewer.user_id)
    assert assigned.status_code == 200
    assert _call(client, reviewer, "mark_reviewed", review).status_code == 200

    _check_state(client, db_session, team, review, "reviewed")
    assert _call(client, approver, "approve", review).status_code == 201

    _check_state(client, db_session, team, review, "approved")
    assert _call(client, approver, "publish", review).status_code == 200

    _check_state(client, db_session, team, review, "published")

    # The outsider gets 404 on every route that names this draft, as for a random id.
    for action in ("view", "audit", *WORKFLOW_ACTIONS, "comment"):
        response = _call(client, team["outsider"], action, review, reviewer.user_id)
        assert response.status_code == 404, (action, response.text)

    # Who did what, from the server's own record.
    trail = _call(client, team["owner"], "audit", review).json()["items"]
    done = [(i["action"], (i["actor"] or {}).get("id")) for i in reversed(trail)]
    for step in (
        ("draft_created", writer.user_id),
        ("draft_submitted", writer.user_id),
        ("review_requested", writer.user_id),
        ("reviewer_assigned", approver.user_id),
        ("reviewed", reviewer.user_id),
        ("approval_granted", approver.user_id),
        ("published", approver.user_id),
    ):
        assert step in done, (step, done)
    denied = [i for i in trail if i["action"] == "approval_denied"]
    assert denied and all(
        i["details"]["code"]
        in {"REVIEW_REQUIRED", "SELF_APPROVAL_FORBIDDEN", "SAME_REVIEWER_APPROVER_FORBIDDEN"}
        for i in denied
    )


def test_author_cannot_publish_their_own_content_in_a_team(client, db_session, team) -> None:
    owner, approver = team["owner"], team["approver"]
    review = client.post(
        "/api/reviews", json={"brand_id": owner.brand_id, "text": CLEAN}, headers=owner.headers
    ).json()
    assert _call(client, approver, "approve", review).status_code == 201
    refused = _call(client, owner, "publish", review)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "SELF_APPROVAL_FORBIDDEN"
    assert _status(db_session, review) == "approved"
    db_session.expire_all()
    denied = (
        db_session.query(AuditEvent)
        .filter_by(
            content_item_id=uuid.UUID(review["content_item_id"]), event_type="approval_denied"
        )
        .one()
    )
    assert denied.details["attempted"] == "publish"
    assert _call(client, approver, "publish", review).status_code == 200


def test_the_solo_flow_still_works_end_to_end(client, force_stub_mode, account_factory) -> None:
    """Sign up -> brand document -> check a draft -> approve -> publish, alone, with no AI provider
    configured (every draft is then medium risk): decisions D1 and P4."""
    solo = account_factory("solo")  # registers and uploads an approved fact sheet
    me = client.get("/api/auth/me", headers=solo.headers).json()
    assert (me["role"], me["workspace"]["is_personal"]) == ("owner", True)
    review = solo.submit()
    assert review["approval_mode"] == "self"
    assert {"approve", "submit", "create_version"} <= set(review["allowed_actions"])
    approved = client.post(
        f"/api/content-versions/{review['content_version_id']}/approve", headers=solo.headers
    )
    assert approved.status_code == 201, approved.text
    published = client.post(
        f"/api/content-versions/{review['content_version_id']}/publish", headers=solo.headers
    )
    assert published.status_code == 200, published.text
    assert published.json()["workflow_status"] == "published"
    trail = client.get(
        f"/api/content/{review['content_item_id']}/audit", headers=solo.headers
    ).json()
    actions = {i["action"]: i for i in trail["items"]}
    assert actions["reviewed"]["details"]["self_review"] is True  # P4, recorded honestly
    assert actions["approval_granted"]["details"]["self_approval"] is True  # D1
