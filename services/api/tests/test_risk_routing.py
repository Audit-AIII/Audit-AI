"""Round 3 Phase 4: risk-based routing and the draft workflow (contracts.md section 19,
docs/governance.md sections 6-7).

Part 1 tests `risk_policy` on plain values (no database). Part 2 runs the workflow through the
real routes in a team workspace - owner (who uploads the fact sheet), writer, reviewer, approver -
with the offline scripted provider giving deterministic verdicts.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from conftest import join_workspace, requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule
from inkloom_api.models import AuditEvent, ContentItem, Finding, ResultCache, Review
from inkloom_api.risk_policy import assess, finding_risk, summary_counts

# --- Part 1: the mapping ------------------------------------------------------------------------


def _f(
    status="supported", reasons=None, human=False, category=None, check_type="retrieval", rule=None
):
    return SimpleNamespace(
        finding_id=uuid.uuid4(),
        verification_status=status,
        review_reasons=reasons,
        requires_human_review=human,
        category=category,
        check_type=check_type,
        rule_type=rule,
    )


def _review(status="needs_human_review", rules_status="complete"):
    return SimpleNamespace(status=status, rules_status=rules_status)


@pytest.mark.parametrize(
    ("finding", "level", "code"),
    [
        (
            _f("contradicted", ["contradicted"], True, "contradicted_claim"),
            "high",
            "contradicted_claim",
        ),
        (_f("conflicting_sources", ["not_enough_evidence"], True), "medium", "conflicting_sources"),
        (_f("unverified", ["error"], True, "engine_error"), "medium", "engine_error"),
        (_f("unverified", None, True, "stub"), "medium", "not_checked"),
        (
            _f("unverified", ["not_enough_evidence"], True, "unsupported_claim"),
            "medium",
            "unverified_claim",
        ),
        (_f("supported", ["weak_evidence"], True), "low", "flagged_for_review"),
        (_f("supported", [], False), "clean", "clean"),
        # Krish's new guard reason codes and anything else unknown: stored as-is, medium.
        (_f("supported", ["property_mismatch"], True), "medium", "unknown_signal"),
        (_f("supported", ["unsupported_clause"], True), "medium", "unknown_signal"),
        (_f("supported", ["invented_reason_42"], False), "medium", "unknown_signal"),
        (_f("made_up_status", None, False), "medium", "unknown_signal"),
    ],
)
def test_section_19_mapping(finding, level: str, code: str) -> None:
    got_level, got_code = finding_risk(finding)
    assert (got_level.value, got_code) == (level, code)


def test_the_draft_takes_its_highest_finding_and_names_every_trigger() -> None:
    contradicted = _f("contradicted", ["contradicted"], True)
    unknown = _f("supported", ["property_mismatch"], True)
    clean = _f("supported", [], False)
    result = assess(_review(), [clean, unknown, contradicted])
    assert (result.level, result.required_reviewer_role) == ("high", "reviewer")
    assert result.reason_code == "contradicted_claim"
    assert [t.finding_id for t in result.triggers] == [
        str(contradicted.finding_id),
        str(unknown.finding_id),
    ]
    assert result.triggers[1].review_reasons == ["property_mismatch"]  # passed through as-is
    assert "contradicted" in result.reason_text and "doesn't know" in result.reason_text


def test_clean_goes_to_an_approver_only() -> None:
    result = assess(_review("completed"), [_f("supported", [], False)])
    assert (result.level, result.required_reviewer_role, result.triggers) == (
        "clean",
        "approver",
        [],
    )
    assert assess(_review("completed"), []).level == "clean"


def test_rules_that_did_not_all_run_are_at_least_medium() -> None:
    result = assess(_review("completed", "incomplete"), [_f("supported", [], False)])
    assert (result.level, result.reason_code) == ("medium", "rules_incomplete")


def test_failed_or_source_changed_checks_block_and_running_ones_wait() -> None:
    for status, code in (("failed", "ai_check_failed"), ("source_changed", "source_changed")):
        result = assess(_review(status), [])
        assert result.blocked and result.level is None and result.reason_code == code
    assert assess(_review("analysing"), []) is None


def test_summary_counts() -> None:
    counts = summary_counts(
        [
            _f("supported"),
            _f("contradicted", human=True),
            _f("unverified", human=True),
            _f("conflicting_sources", human=True),
            _f("made_up_status"),  # unknown counts as unverified
            _f("not_applicable", check_type="rule", rule="emoji_run", human=True),
        ]
    )
    assert counts == {
        "supported": 1,
        "contradicted": 1,
        "unverified": 2,
        "conflicting": 1,
        "tone": 1,
        "needs_human_review": 4,
    }


# --- Part 2: the workflow through the routes ---------------------------------------------------

SUPPORTED = ScriptedRule(
    "playback per charge", "SUPPORTED", "up to 12 hours of playback per charge"
)
CONTRADICTED = ScriptedRule(
    "24 hours of playback",
    "CONTRADICTED",
    "up to 12 hours of playback per charge",
    "The fact sheet gives 12 hours.",
)
CLEAN_TEXT = "Lumen Pods offer up to 12 hours of playback per charge."
RISKY_TEXT = "Lumen Pods offer up to 24 hours of playback per charge."


@pytest.fixture
def team(client, monkeypatch, account_factory):
    use_scripted_provider(monkeypatch, [CONTRADICTED, SUPPORTED])
    owner = account_factory("owner")
    members = {}
    for role in ("writer", "reviewer", "approver"):
        members[role] = account_factory(role, with_source=False)
        join_workspace(client, owner, members[role], role)
    return SimpleNamespace(owner=owner, **members)


def _draft(client, author, brand_id, text):
    response = client.post(
        "/api/reviews", json={"brand_id": brand_id, "text": text}, headers=author.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post(client, actor, path, body=None):
    return client.post(path, json=body, headers=actor.headers)


def _submit(client, actor, review):
    return _post(
        client,
        actor,
        f"/api/content/{review['content_item_id']}/submit",
        {"content_version_id": review["content_version_id"]},
    )


def _mark_reviewed(client, actor, review, note="Checked against the fact sheet."):
    return _post(
        client,
        actor,
        f"/api/content/{review['content_item_id']}/mark-reviewed",
        {"content_version_id": review["content_version_id"], "note": note},
    )


def _approve(client, actor, review):
    return _post(client, actor, f"/api/content-versions/{review['content_version_id']}/approve")


def _publish(client, actor, review):
    return _post(client, actor, f"/api/content-versions/{review['content_version_id']}/publish")


def _view(client, actor, review):
    return client.get(f"/api/reviews/{review['id']}", headers=actor.headers).json()


def _code(response):
    return response.json()["error"]["code"]


def _events(db_session, item_id: str) -> list[str]:
    db_session.expire_all()
    return [
        e.event_type
        for e in db_session.query(AuditEvent)
        .filter_by(content_item_id=uuid.UUID(item_id))
        .order_by(AuditEvent.created_at)
    ]


@requires_db
def test_contradicted_draft_cannot_be_approved_or_published_until_reviewed(
    client, team, db_session
) -> None:
    draft = _draft(client, team.writer, team.owner.brand_id, RISKY_TEXT)
    assert (draft["workflow_status"], draft["risk_level"]) == ("draft", "high")

    submitted = _submit(client, team.writer, draft)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["workflow_status"] == "in_review"
    assert submitted.json()["routing_reason"]["code"] == "contradicted_claim"

    seen = _view(client, team.approver, draft)
    assert "approve" not in seen["allowed_actions"] and "publish" not in seen["allowed_actions"]
    for attempt in (_approve, _publish):
        refused = attempt(client, team.approver, draft)
        assert refused.status_code == 409 and _code(refused) == "REVIEW_REQUIRED", refused.text
        assert "contradicted" in refused.json()["error"]["message"]
    db_session.expire_all()
    item = db_session.get(ContentItem, uuid.UUID(draft["content_item_id"]))
    assert item.workflow_status == "in_review"
    review = db_session.get(Review, uuid.UUID(draft["id"]))
    assert review.status == "needs_human_review"

    assert "mark_reviewed" in _view(client, team.reviewer, draft)["allowed_actions"]
    reviewed = _mark_reviewed(client, team.reviewer, draft)
    assert reviewed.status_code == 200 and reviewed.json()["workflow_status"] == "reviewed"

    assert "approve" in _view(client, team.approver, draft)["allowed_actions"]
    assert _approve(client, team.approver, draft).status_code == 201
    assert _publish(client, team.writer, draft).status_code == 403  # writers don't publish
    published = _publish(client, team.approver, draft)
    assert published.status_code == 200 and published.json()["workflow_status"] == "published"

    assert _events(db_session, draft["content_item_id"]) == [
        "draft_submitted",
        "routing_decision",
        "review_requested",
        "approval_denied",
        "approval_denied",
        "reviewed",
        "content_version.approved",
        "published",
    ]


@requires_db
def test_clean_draft_goes_to_an_approver_without_a_review_step(client, team, db_session) -> None:
    draft = _draft(client, team.writer, team.owner.brand_id, CLEAN_TEXT)
    assert (draft["risk_level"], draft["required_reviewer_role"]) == ("clean", "approver")
    submitted = _submit(client, team.writer, draft)
    assert submitted.json()["workflow_status"] == "submitted"
    assert "mark_reviewed" not in _view(client, team.reviewer, draft)["allowed_actions"]
    assert _approve(client, team.approver, draft).status_code == 201

    # D4: a clean draft approved straight from `draft` is submitted in the same step.
    direct = _draft(client, team.writer, team.owner.brand_id, CLEAN_TEXT)
    assert _approve(client, team.approver, direct).status_code == 201
    db_session.expire_all()
    submitted_event = (
        db_session.query(AuditEvent)
        .filter_by(
            content_item_id=uuid.UUID(direct["content_item_id"]), event_type="draft_submitted"
        )
        .one()
    )
    assert submitted_event.details["implicit"] is True
    assert (
        db_session.get(ContentItem, uuid.UUID(direct["content_item_id"])).workflow_status
        == "approved"
    )


@requires_db
def test_findings_that_change_after_submission_re_route_the_draft(
    client, team, monkeypatch, db_session
) -> None:
    draft = _draft(client, team.writer, team.owner.brand_id, CLEAN_TEXT)
    assert _submit(client, team.writer, draft).json()["workflow_status"] == "submitted"

    # The same claim now comes back contradicted (e.g. the model or the sources changed).
    use_scripted_provider(
        monkeypatch,
        [
            ScriptedRule(
                "playback per charge", "CONTRADICTED", "up to 12 hours of playback per charge"
            )
        ],
    )
    db_session.query(ResultCache).delete()  # a real change of verdict, not a cached replay
    db_session.commit()
    rerun = _post(client, team.reviewer, f"/api/reviews/{draft['id']}/rerun")
    assert rerun.status_code == 201, rerun.text
    body = rerun.json()
    assert (body["workflow_status"], body["risk_level"]) == ("in_review", "high")
    assert _approve(client, team.approver, body).status_code == 409
    db_session.expire_all()
    rerouted = (
        db_session.query(AuditEvent)
        .filter_by(
            content_item_id=uuid.UUID(draft["content_item_id"]), event_type="routing_decision"
        )
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert rerouted.details["rerouted"] is True
    assert rerouted.details["after"] == {"workflow_status": "in_review"}


@requires_db
def test_unknown_statuses_and_reason_codes_route_conservatively(client, team, db_session) -> None:
    draft = _draft(client, team.writer, team.owner.brand_id, CLEAN_TEXT)
    # An engine that grew a new status and Krish's new guard reasons: written straight to the row.
    finding = db_session.get(Finding, uuid.UUID(draft["findings"][0]["finding_id"]))
    finding.verification_status = "partially_supported"
    finding.review_reasons = ["property_mismatch", "unsupported_clause", "something_new"]
    item = db_session.get(ContentItem, uuid.UUID(draft["content_item_id"]))
    item.routed_review_id = None  # stored routing is now out of date
    db_session.commit()

    seen = _view(client, team.approver, draft)
    assert seen["findings"][0]["verification_status"] == "partially_supported"  # passed through
    assert seen["findings"][0]["review_reasons"] == [
        "property_mismatch",
        "unsupported_clause",
        "something_new",
    ]
    assert (seen["risk_level"], seen["required_reviewer_role"]) == ("medium", "reviewer")
    assert seen["routing_reason"]["code"] == "unknown_signal"
    assert seen["summary_counts"]["unverified"] == 1
    assert "approve" not in seen["allowed_actions"]
    assert _approve(client, team.approver, draft).status_code == 409
    submitted = _submit(client, team.writer, draft)
    assert submitted.status_code == 200 and submitted.json()["workflow_status"] == "in_review"


@requires_db
def test_separation_of_duties_d6(client, team) -> None:
    # The owner wrote this draft: they can't review it while a reviewer exists ...
    own = _draft(client, team.owner, team.owner.brand_id, RISKY_TEXT)
    assert _submit(client, team.owner, own).status_code == 200
    refused = _mark_reviewed(client, team.owner, own)
    assert refused.status_code == 403 and _code(refused) == "SELF_REVIEW_FORBIDDEN"

    # ... and whoever marked a draft reviewed doesn't approve it while another approver exists.
    other = _draft(client, team.writer, team.owner.brand_id, RISKY_TEXT)
    assert _submit(client, team.writer, other).status_code == 200
    assert _mark_reviewed(client, team.owner, other).status_code == 200
    assert "approve" not in _view(client, team.owner, other)["allowed_actions"]
    same = _approve(client, team.owner, other)
    assert same.status_code == 403 and _code(same) == "SAME_REVIEWER_APPROVER_FORBIDDEN"
    assert _approve(client, team.approver, other).status_code == 201


@requires_db
def test_assigning_a_reviewer(client, team) -> None:
    draft = _draft(client, team.writer, team.owner.brand_id, RISKY_TEXT)
    path = f"/api/content/{draft['content_item_id']}/assign"
    early = _post(client, team.approver, path, {"reviewer_user_id": team.reviewer.user_id})
    assert early.status_code == 409 and _code(early) == "INVALID_TRANSITION"  # not submitted yet
    assert _submit(client, team.writer, draft).status_code == 200

    assert (
        _post(client, team.writer, path, {"reviewer_user_id": team.reviewer.user_id}).status_code
        == 403
    )
    author = _post(client, team.approver, path, {"reviewer_user_id": team.writer.user_id})
    assert author.status_code == 422  # a writer can't review, and authors never review own work
    other = _post(client, team.reviewer, path, {"reviewer_user_id": team.owner.user_id})
    assert other.status_code == 403  # a reviewer assigns only themself

    taken = _post(client, team.reviewer, path, {"reviewer_user_id": team.reviewer.user_id})
    assert taken.status_code == 200, taken.text
    assert taken.json()["assigned_reviewer"]["id"] == team.reviewer.user_id
    seen = _view(client, team.writer, draft)
    assert seen["assigned_reviewer"] == {
        "id": team.reviewer.user_id,
        "display_name": seen["assigned_reviewer"]["display_name"],
    }
    assert seen["author"]["id"] == team.writer.user_id
    assert seen["workspace"]["is_personal"] is True  # the owner's personal workspace, shared


@requires_db
def test_blocked_drafts_must_be_re_checked(client, team, db_session) -> None:
    draft = _draft(client, team.writer, team.owner.brand_id, CLEAN_TEXT)
    review = db_session.get(Review, uuid.UUID(draft["id"]))
    review.status = "failed"
    item = db_session.get(ContentItem, uuid.UUID(draft["content_item_id"]))
    item.workflow_status = "blocked"
    db_session.commit()
    refused = _submit(client, team.writer, draft)
    assert refused.status_code == 409 and _code(refused) == "INVALID_TRANSITION"
    rerun = _post(client, team.writer, f"/api/reviews/{draft['id']}/rerun")
    assert rerun.json()["workflow_status"] == "draft"


@requires_db
def test_a_changed_source_blocks_an_approved_draft(client, team) -> None:
    draft = _draft(client, team.writer, team.owner.brand_id, CLEAN_TEXT)
    assert _approve(client, team.approver, draft).status_code == 201
    withdrawn = _post(
        client,
        team.owner,
        f"/api/brands/{team.owner.brand_id}/sources/{team.owner.source_id}/withdraw",
        {"status": "archived", "reason": "outdated figures"},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    seen = _view(client, team.approver, draft)
    assert seen["workflow_status"] == "blocked"
    assert seen["routing_reason"]["code"] == "source_changed"
    assert _publish(client, team.approver, draft).status_code == 409


@requires_db
def test_a_new_version_starts_the_workflow_again(client, team) -> None:
    draft = _draft(client, team.writer, team.owner.brand_id, CLEAN_TEXT)
    assert _approve(client, team.approver, draft).status_code == 201
    edited = _post(
        client,
        team.writer,
        f"/api/content/{draft['content_item_id']}/versions",
        {"text": "Lumen Pods now offer up to 12 hours of playback per charge."},
    )
    assert edited.status_code == 201
    assert edited.json()["review"]["workflow_status"] == "draft"
    # It was submitted before (implicitly, when approved), so the action is offered as resubmit.
    assert "resubmit" in edited.json()["review"]["allowed_actions"]
