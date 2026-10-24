"""Phase 7: Intent-lock enforced by the server, per-finding Dismiss, and comments on findings
(DESIGN.md §21-22; services/verification/HANDOFF_STEPS_6_8.md, Step 7).

Intent-lock
1. locks are set per content version, validated with the engine's rules; another account's
   version is a 404; the audit event never records the phrases;
   -> test_locks_api_validation_and_scope
2. a suggestion that would remove a locked phrase is never offered - withheld when the lock was
   set after the review ran, not produced when it was set before;
   -> test_lock_set_after_review_withholds_and_rerun_respects_it
3. it can't be bypassed: an engine that ignores the locks still gets nothing stored;
   -> test_backend_drops_lock_breaking_correction_even_if_engine_ignores_locks
   -> test_backend_drops_lock_breaking_safer_wording_even_if_engine_ignores_locks
   -> test_rule_suggestion_that_breaks_a_lock_is_not_offered
4. a new version inherits the locks; locks are part of the result-cache key;
   -> test_new_version_inherits_locks_and_locks_change_the_cache_key
Dismiss
5. dismissing records a separate decision and changes nothing about the finding or the review;
   restore undoes it; repeating either is a 409; both are audited;
   -> test_dismiss_and_restore_never_touch_the_finding
6. two dismisses at once: one wins, the other is a 409;
   -> test_concurrent_dismisses_record_one_decision
Comments
7. comments are listed oldest first and counted on the finding; invalid ones are a 422; the audit
   event never records the text;
   -> test_comments_on_a_finding
8. another account can't dismiss, restore, read or add comments: 404 like a random id.
   -> test_other_accounts_findings_are_unreachable
"""

from __future__ import annotations

import threading
import uuid

from conftest import requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule
from inkloom_api.models import AuditEvent, ContentVersion, Finding, FindingDecision

CLAIM = "Lumen Pods offer up to 24 hours of playback per charge."
CORRECTABLE = [
    ScriptedRule(
        "24 hours of playback per charge",
        "CONTRADICTED",
        "up to 12 hours of playback per charge",
        "The fact sheet gives 12 hours.",
        correction=("24 hours", "12 hours"),
    ),
    ScriptedRule(
        "12 hours of playback per charge",
        "SUPPORTED",
        "up to 12 hours of playback per charge",
        "12 hours.",
    ),
]
CORRECTED = "Lumen Pods offer up to 12 hours of playback per charge."


def _put_locks(client, account, version_id: str, locks):
    return client.put(
        f"/api/content-versions/{version_id}/locks",
        json={"locked_phrases": locks},
        headers=account.headers,
    )


def _claim_finding(review: dict) -> dict:
    [finding] = [f for f in review["findings"] if f["check_type"] != "rule"]
    return finding


def _audit(db_session, account, prefix: str) -> list[AuditEvent]:
    db_session.expire_all()
    return (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.organisation_id == uuid.UUID(account.organisation_id),
            AuditEvent.event_type.like(f"{prefix}%"),
        )
        .order_by(AuditEvent.created_at)
        .all()
    )


# --- Intent-lock ---------------------------------------------------------------------------------


@requires_db
def test_locks_api_validation_and_scope(
    client, force_stub_mode, db_session, account_factory
) -> None:
    owner, other = account_factory("owner"), account_factory("other")
    version = owner.submit()["content_version_id"]

    saved = _put_locks(client, owner, version, ["₹2,499", "Lumen Pods", "₹2,499"])
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "content_version_id": version,
        "locked_phrases": ["₹2,499", "Lumen Pods"],
    }  # deduplicated
    assert (
        client.get(f"/api/content-versions/{version}/locks", headers=owner.headers).json()
        == saved.json()
    )
    review = client.get("/api/reviews", headers=owner.headers).json()[0]
    assert review["locked_phrases"] == ["₹2,499", "Lumen Pods"]

    for bad in ([" "], ["x" * 201], [f"p{i}" for i in range(51)], ["a\x00b"]):
        response = _put_locks(client, owner, version, bad)
        assert (
            response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
        ), bad
    assert (
        client.put(
            f"/api/content-versions/{version}/locks",
            json={"locked_phrases": "Lumen"},
            headers=owner.headers,
        ).status_code
        == 422
    )
    assert _put_locks(client, other, version, ["x"]).status_code == 404
    assert (
        client.get(f"/api/content-versions/{version}/locks", headers=other.headers).status_code
        == 404
    )
    assert client.get(f"/api/content-versions/{version}/locks", headers=owner.headers).json()[
        "locked_phrases"
    ] == ["₹2,499", "Lumen Pods"]

    [event] = _audit(db_session, owner, "content_version.locks_updated")
    assert event.details == {"count": 2}  # never the phrases


@requires_db
def test_lock_set_after_review_withholds_and_rerun_respects_it(
    client, monkeypatch, account_factory
) -> None:
    use_scripted_provider(monkeypatch, CORRECTABLE)
    owner = account_factory("owner")
    review = owner.submit(CLAIM)
    assert _claim_finding(review)["suggested_correction"] == CORRECTED

    assert _put_locks(client, owner, review["content_version_id"], ["24 hours"]).status_code == 200
    finding = _claim_finding(
        client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json()
    )
    assert finding["suggested_correction"] is None and finding["withheld_by_intent_lock"] is True
    assert finding["verification_status"] == "contradicted"  # the verdict is untouched

    rerun = client.post(f"/api/reviews/{review['id']}/rerun", headers=owner.headers).json()
    finding = _claim_finding(rerun)
    assert finding["verification_status"] == "contradicted"
    assert (
        finding["suggested_correction"] is None and finding["withheld_by_intent_lock"] is False
    )  # never produced

    # Unlocking makes the stored suggestion of the first review visible again: it was withheld,
    # never deleted.
    assert _put_locks(client, owner, review["content_version_id"], []).status_code == 200
    assert (
        _claim_finding(client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json())[
            "suggested_correction"
        ]
        == CORRECTED
    )


@requires_db
def test_backend_drops_lock_breaking_correction_even_if_engine_ignores_locks(
    client, monkeypatch, db_session, account_factory
) -> None:
    from inkloom_verify.correction import ClaimCorrector

    use_scripted_provider(monkeypatch, CORRECTABLE)
    real_correct = ClaimCorrector.correct
    monkeypatch.setattr(
        ClaimCorrector,
        "correct",
        lambda self, result, content, locks=(): real_correct(self, result, content),
    )

    owner = account_factory("owner")
    first = owner.submit(CLAIM)
    _put_locks(client, owner, first["content_version_id"], ["24 hours"])
    rerun = client.post(f"/api/reviews/{first['id']}/rerun", headers=owner.headers).json()
    finding = _claim_finding(rerun)
    assert finding["suggested_correction"] is None and finding["withheld_by_intent_lock"] is False

    db_session.expire_all()
    stored = db_session.get(Finding, uuid.UUID(finding["finding_id"]))
    assert stored.suggested_correction is None  # dropped before storing, not just hidden


@requires_db
def test_backend_drops_lock_breaking_safer_wording_even_if_engine_ignores_locks(
    client, monkeypatch, db_session, account_factory
) -> None:
    from inkloom_verify.softening import ClaimSoftener

    from inkloom_api.engine import pipeline

    claim = "The Kora X2 is India's number one smartphone."
    use_scripted_provider(
        monkeypatch,
        [
            ScriptedRule(
                "number one",
                "NOT_ENOUGH_EVIDENCE",
                None,
                "No rankings.",
                correction=("India's number one smartphone", "a smartphone sold in India"),
            )
        ],
    )

    class IgnoresLocks(ClaimSoftener):
        def soften(self, result, content, locked_phrases=()):
            return super().soften(result, content)

    monkeypatch.setattr(pipeline, "load_softener_class", lambda: IgnoresLocks)
    owner = account_factory("owner")
    first = owner.submit(claim)
    assert _claim_finding(first)["safer_wording"] == "The Kora X2 is a smartphone sold in India."

    _put_locks(client, owner, first["content_version_id"], ["number one"])
    finding = _claim_finding(
        client.post(f"/api/reviews/{first['id']}/rerun", headers=owner.headers).json()
    )
    assert finding["verification_status"] == "unverified" and finding["safer_wording"] is None
    db_session.expire_all()
    assert db_session.get(Finding, uuid.UUID(finding["finding_id"])).safer_wording is None


@requires_db
def test_rule_suggestion_that_breaks_a_lock_is_not_offered(
    client, monkeypatch, account_factory
) -> None:
    use_scripted_provider(monkeypatch, CORRECTABLE)
    owner = account_factory("owner")
    client.put(
        f"/api/brands/{owner.brand_id}/rules",
        headers=owner.headers,
        json={
            "rules": {
                "prohibited_terms": [
                    {
                        "rule_id": "no-guarantee",
                        "term": "guaranteed",
                        "approved_alternative": "designed",
                    }
                ]
            }
        },
    )
    first = owner.submit(f"Guaranteed comfort. {CORRECTED}")
    [rule] = [f for f in first["findings"] if f["check_type"] == "rule"]
    assert rule["suggested_correction"] == "designed"

    _put_locks(client, owner, first["content_version_id"], ["Guaranteed comfort"])
    rerun = client.post(f"/api/reviews/{first['id']}/rerun", headers=owner.headers).json()
    [rule] = [f for f in rerun["findings"] if f["check_type"] == "rule"]
    assert rule["rule_id"] == "no-guarantee"  # still reported...
    assert (
        rule["suggested_correction"] is None and rule["suggestion_basis"] is None
    )  # ...but no lock-breaking fix


@requires_db
def test_new_version_inherits_locks_and_locks_change_the_cache_key(
    client, monkeypatch, db_session, account_factory
) -> None:
    use_scripted_provider(monkeypatch, CORRECTABLE)
    owner = account_factory("owner")
    first = owner.submit(CLAIM)
    assert (
        client.post(f"/api/reviews/{first['id']}/rerun", headers=owner.headers).json()[
            "served_from_cache"
        ]
        is True
    )

    _put_locks(client, owner, first["content_version_id"], ["Lumen Pods"])
    after_lock = client.post(f"/api/reviews/{first['id']}/rerun", headers=owner.headers).json()
    assert (
        after_lock["served_from_cache"] is False
    )  # locks can change the suggestions, so no stale replay

    edited = client.post(
        f"/api/content/{first['content_item_id']}/versions",
        json={"text": CORRECTED},
        headers=owner.headers,
    ).json()
    db_session.expire_all()
    assert db_session.get(
        ContentVersion, uuid.UUID(str(edited["content_version_id"]))
    ).locked_phrases == ["Lumen Pods"]
    assert edited["review"]["locked_phrases"] == ["Lumen Pods"]


# --- Dismiss -------------------------------------------------------------------------------------


@requires_db
def test_dismiss_and_restore_never_touch_the_finding(
    client, monkeypatch, db_session, account_factory
) -> None:
    use_scripted_provider(monkeypatch, CORRECTABLE)
    owner = account_factory("owner")
    review = owner.submit(CLAIM)
    before = _claim_finding(review)
    url = f"/api/findings/{before['finding_id']}"

    dismissed = client.post(
        f"{url}/dismiss", json={"note": "we say 24h in the US ad"}, headers=owner.headers
    )
    assert dismissed.status_code == 201, dismissed.text
    assert (
        dismissed.json()["action"] == "dismissed"
        and dismissed.json()["actor_user_id"] == owner.user_id
    )

    after = client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json()
    finding = _claim_finding(after)
    assert (
        finding["dismissal"]["by_user_id"] == owner.user_id
        and finding["dismissal"]["note"] == "we say 24h in the US ad"
    )
    unchanged = (
        "verification_status",
        "evidence",
        "explanation",
        "suggested_correction",
        "severity",
        "category",
    )
    assert {k: finding[k] for k in unchanged} == {k: before[k] for k in unchanged}
    assert finding["verification_status"] == "contradicted"  # dismissed is not "supported"
    assert after["status"] == review["status"]  # the review is not decided by dismissing

    again = client.post(f"{url}/dismiss", headers=owner.headers)
    assert (
        again.status_code == 409
        and again.json()["error"]["message"] == "this finding is already dismissed"
    )
    assert client.post(f"{url}/restore", headers=owner.headers).status_code == 201
    assert (
        _claim_finding(client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json())[
            "dismissal"
        ]
        is None
    )
    assert (
        client.post(f"{url}/restore", headers=owner.headers).json()["error"]["message"]
        == "this finding is not dismissed"
    )

    assert [e.event_type for e in _audit(db_session, owner, "finding.")] == [
        "finding.dismissed",
        "finding.restored",
    ]


@requires_db
def test_concurrent_dismisses_record_one_decision(
    client, force_stub_mode, db_session, account_factory
) -> None:
    owner = account_factory("owner")
    finding_id = owner.submit()["findings"][0]["finding_id"]
    statuses: list[int] = []
    threads = [
        threading.Thread(
            target=lambda: statuses.append(
                client.post(
                    f"/api/findings/{finding_id}/dismiss", headers=owner.headers
                ).status_code
            )
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(statuses) == [201, 409]
    db_session.expire_all()
    assert (
        db_session.query(FindingDecision).filter_by(finding_id=uuid.UUID(finding_id)).count() == 1
    )


# --- Comments ------------------------------------------------------------------------------------


@requires_db
def test_comments_on_a_finding(client, force_stub_mode, db_session, account_factory) -> None:
    owner = account_factory("owner")
    review = owner.submit()
    url = f"/api/findings/{review['findings'][0]['finding_id']}/comments"
    assert client.get(url, headers=owner.headers).json() == []

    for text in ("Check with legal.", "Legal says fine."):
        created = client.post(url, json={"body": text}, headers=owner.headers)
        assert created.status_code == 201, created.text
        assert created.json()["author_user_id"] == owner.user_id
    assert [c["body"] for c in client.get(url, headers=owner.headers).json()] == [
        "Check with legal.",
        "Legal says fine.",
    ]
    assert (
        client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json()["findings"][0][
            "comment_count"
        ]
        == 2
    )

    for bad in ("   ", "a\x00b", "x" * 2001):
        assert client.post(url, json={"body": bad}, headers=owner.headers).status_code == 422, bad
    events = _audit(db_session, owner, "finding.commented")
    assert len(events) == 2 and all(
        "body" not in e.details and "Legal" not in str(e.details) for e in events
    )


@requires_db
def test_other_accounts_findings_are_unreachable(client, force_stub_mode, account_factory) -> None:
    owner, other = account_factory("owner"), account_factory("other")
    finding_id = owner.submit()["findings"][0]["finding_id"]
    for target in (finding_id, str(uuid.uuid4())):
        for method, path, body in (
            ("POST", "dismiss", None),
            ("POST", "restore", None),
            ("GET", "comments", None),
            ("POST", "comments", {"body": "hi"}),
        ):
            response = client.request(
                method, f"/api/findings/{target}/{path}", json=body, headers=other.headers
            )
            assert (
                response.status_code == 404
                and response.json()["error"]["message"] == "finding not found"
            ), (path, target)
    review = client.get("/api/reviews", headers=owner.headers).json()[0]
    assert (
        review["findings"][0]["dismissal"] is None and review["findings"][0]["comment_count"] == 0
    )
