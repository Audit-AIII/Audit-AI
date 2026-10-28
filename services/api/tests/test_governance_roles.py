"""Round 3 Phase 2: roles enforced by the real routes (docs/governance.md section 5).

One team workspace per test: an owner (who also uploads the brand's fact sheet), plus a writer,
a reviewer and an approver who joined by invitation, and an outsider in a workspace of their own.
Every review runs in stub mode, which always finishes `needs_human_review` with one finding, so
each draft can be decided on, commented on and dismissed.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass

import pytest

from conftest import Account, join_workspace, requires_db

pytestmark = requires_db


@dataclass
class Team:
    owner: Account
    writer: Account
    reviewer: Account
    approver: Account
    outsider: Account

    def member(self, role: str) -> Account:
        return getattr(self, role)


@pytest.fixture
def team(client, force_stub_mode, account_factory) -> Team:
    owner = account_factory("owner")
    members = {}
    for role in ("writer", "reviewer", "approver"):
        members[role] = account_factory(role, with_source=False)
        join_workspace(client, owner, members[role], role)
    outsider = account_factory("outsider")
    return Team(owner=owner, outsider=outsider, **members)


def _draft(client, author: Account, brand_id: str, text: str = "Lumen Pods have 2 years.") -> dict:
    response = client.post(
        "/api/reviews", json={"brand_id": brand_id, "text": text}, headers=author.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _do(client, actor: Account, action: str, review: dict):
    """Performs one `allowed_actions` value through its real route."""
    cv = review["content_version_id"]
    finding = review["findings"][0]["finding_id"]
    calls = {
        "create_version": lambda: client.post(
            f"/api/content/{review['content_item_id']}/versions",
            json={"text": "Lumen Pods have a 2-year warranty."},
            headers=actor.headers,
        ),
        "rerun": lambda: client.post(f"/api/reviews/{review['id']}/rerun", headers=actor.headers),
        "approve": lambda: client.post(
            f"/api/content-versions/{cv}/approve", headers=actor.headers
        ),
        "request_changes": lambda: client.post(
            f"/api/content-versions/{cv}/request-changes",
            json={"decision": "changes_requested"},
            headers=actor.headers,
        ),
        "reject": lambda: client.post(
            f"/api/content-versions/{cv}/request-changes",
            json={"decision": "rejected"},
            headers=actor.headers,
        ),
        "comment": lambda: client.post(
            f"/api/findings/{finding}/comments", json={"body": "Looks off."}, headers=actor.headers
        ),
        "dismiss_finding": lambda: client.post(
            f"/api/findings/{finding}/dismiss", json={"note": "fine"}, headers=actor.headers
        ),
    }
    return calls[action]()


REVIEW_ACTIONS = (
    "create_version",
    "rerun",
    "approve",
    "request_changes",
    "reject",
    "comment",
    "dismiss_finding",
)
EXPECTED_ON_WRITERS_DRAFT = {
    "owner": set(REVIEW_ACTIONS),
    "approver": {"rerun", "approve", "request_changes", "reject", "comment", "dismiss_finding"},
    "reviewer": {"rerun", "request_changes", "comment", "dismiss_finding"},
    "writer": {"create_version", "rerun", "comment"},  # the writer's own draft: never approve
}


@pytest.mark.parametrize("role", sorted(EXPECTED_ON_WRITERS_DRAFT))
def test_allowed_actions_match_what_the_server_permits(client, team: Team, role: str) -> None:
    """For each role: `allowed_actions` on a writer's draft is the documented set, and each of
    the seven actions succeeds through its route exactly when it is listed (a fresh draft per
    action, so one action's effect can't change another's answer)."""
    actor = team.member(role)
    listed = None
    for action in REVIEW_ACTIONS:
        draft = _draft(client, team.writer, team.owner.brand_id, f"Draft for {role}/{action}.")
        seen = client.get(f"/api/reviews/{draft['id']}", headers=actor.headers).json()
        if listed is None:
            listed = set(seen["allowed_actions"])
            assert listed == EXPECTED_ON_WRITERS_DRAFT[role]
            assert seen["is_current_version"] is True
        response = _do(client, actor, action, seen)
        if action in listed:
            assert response.status_code in (200, 201), (role, action, response.text)
        else:
            assert response.status_code == 403, (role, action, response.text)
            assert response.json()["error"]["code"] == "FORBIDDEN"


def test_writer_cannot_touch_another_writers_draft(client, team: Team) -> None:
    # A second writer without a sixth sign-up (registration is rate-limited per address).
    second_writer = team.approver
    changed = client.patch(
        f"/api/workspace/members/{second_writer.user_id}",
        json={"role": "writer"},
        headers=team.owner.headers,
    )
    assert changed.status_code == 200, changed.text
    draft = _draft(client, team.writer, team.owner.brand_id)

    seen = client.get(f"/api/reviews/{draft['id']}", headers=second_writer.headers).json()
    assert seen["allowed_actions"] == ["comment"]
    for action in ("create_version", "rerun"):
        assert _do(client, second_writer, action, seen).status_code == 403, action
    locks = client.put(
        f"/api/content-versions/{draft['content_version_id']}/locks",
        json={"locked_phrases": ["Lumen Pods"]},
        headers=second_writer.headers,
    )
    assert locks.status_code == 403
    own_locks = client.put(
        f"/api/content-versions/{draft['content_version_id']}/locks",
        json={"locked_phrases": ["Lumen Pods"]},
        headers=team.writer.headers,
    )
    assert own_locks.status_code == 200, own_locks.text


def _upload(client, actor: Account, brand_id: str):
    return client.post(
        f"/api/brands/{brand_id}/sources",
        data={"title": "Extra facts", "approve": "true"},
        files={"file": ("f.txt", io.BytesIO(b"Warranty: 2 years."), "text/plain")},
        headers=actor.headers,
    )


@pytest.mark.parametrize(
    ("role", "manages_brand_knowledge", "creates_drafts", "runs_evaluations"),
    [
        ("owner", True, True, True),
        ("approver", True, False, False),
        ("reviewer", False, False, False),
        ("writer", False, True, False),
    ],
)
def test_workspace_level_routes(
    client,
    team: Team,
    role: str,
    manages_brand_knowledge: bool,
    creates_drafts: bool,
    runs_evaluations: bool,
) -> None:
    actor = team.member(role)
    brand_id = team.owner.brand_id

    def allowed(response) -> bool:
        assert response.status_code != 404, response.text
        return response.status_code != 403

    assert allowed(_upload(client, actor, brand_id)) is manages_brand_knowledge
    created_brand = client.post(
        "/api/brands", json={"name": f"Brand by {role}"}, headers=actor.headers
    )
    assert allowed(created_brand) is manages_brand_knowledge
    rules = client.put(f"/api/brands/{brand_id}/rules", json={"rules": None}, headers=actor.headers)
    assert allowed(rules) is manages_brand_knowledge
    draft = client.post(
        "/api/reviews", json={"brand_id": brand_id, "text": "A draft."}, headers=actor.headers
    )
    assert allowed(draft) is creates_drafts
    # Stub mode: an owner gets past the permission check and is refused for having no provider.
    evaluation = client.post("/api/evaluations", headers=actor.headers)
    assert allowed(evaluation) is runs_evaluations

    # Reading is open to every member.
    for path in (
        "/api/brands",
        f"/api/brands/{brand_id}/sources",
        f"/api/brands/{brand_id}/rules",
        "/api/reviews",
        "/api/analytics/brand-risk",
    ):
        assert client.get(path, headers=actor.headers).status_code == 200, (role, path)


def test_outsider_gets_not_found_on_every_draft_route(client, team: Team) -> None:
    """The outsider owns their own workspace (so passes every role check) and still can't reach
    a draft in the team's: each route answers 404, the same as a random id."""
    draft = _draft(client, team.writer, team.owner.brand_id)
    assert client.get(f"/api/reviews/{draft['id']}", headers=team.outsider.headers).status_code == (
        404
    )
    for action in REVIEW_ACTIONS:
        response = _do(client, team.outsider, action, draft)
        assert response.status_code == 404, (action, response.text)
        assert response.json()["error"]["code"] == "NOT_FOUND"
    listed = client.get("/api/reviews", headers=team.outsider.headers).json()
    assert draft["id"] not in {r["id"] for r in listed}
    assert _upload(client, team.outsider, team.owner.brand_id).status_code == 404


def test_refused_actions_change_nothing(client, team: Team, db_session) -> None:
    from inkloom_api.models import ApprovalEvent, Review

    draft = _draft(client, team.writer, team.owner.brand_id)
    for actor, action in (
        (team.writer, "approve"),
        (team.reviewer, "approve"),
        (team.reviewer, "reject"),
        (team.writer, "request_changes"),
    ):
        assert _do(client, actor, action, draft).status_code == 403
    db_session.expire_all()
    review = db_session.get(Review, uuid.UUID(draft["id"]))
    assert review.status == "needs_human_review"
    assert db_session.query(ApprovalEvent).filter_by(review_id=review.id).count() == 0
