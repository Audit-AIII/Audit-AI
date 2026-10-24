"""Phase 4: Member 2's terminology / compliance / accessibility rules wired into reviews
(services/verification/RULES_HANDOFF.md; backend side in engine/brand_rules.py).

1. with no brand rules, the default accessibility checks run: a violation is a rule finding in
   the agreed shape, and checks that had nothing to inspect are "not_checkable", never "passed";
   -> test_default_accessibility_checks_run_with_no_brand_rules
2. a clean draft completes; rules don't force review when nothing was violated;
   -> test_clean_draft_completes_and_unchecked_is_not_passed
3. brand rules saved through the API produce terminology findings with the configured
   suggestion; every save is versioned and audited; null clears them;
   -> test_brand_rules_api_and_terminology_finding
4. a rule quoted from an approved document carries that document as evidence; a quote that
   isn't in one of the brand's approved documents is dropped, with the suggestion it justified;
   -> test_rule_evidence_is_kept_only_if_it_is_really_in_an_approved_document
5. malformed, contradictory or NUL-containing rules are refused when saved (422, nothing
   stored, no configured value echoed); another account's brand is a 404;
   -> test_invalid_rules_are_refused_when_saved
   -> test_other_accounts_rules_are_unreachable
6. rules that no longer validate, or a rules-engine crash, are "not_applied": no finding is made
   up, the claim checks still run, a person reviews it; a check that errors is "incomplete";
   -> test_stored_rules_that_no_longer_validate_are_not_applied
   -> test_rules_engine_crash_fabricates_nothing
   -> test_a_check_that_errors_makes_the_rules_incomplete
7. rules run with no provider and with no approved sources;
   -> test_rules_run_without_a_provider_and_without_sources
8. rule findings are never cached: a cached review still gets the current rules' findings.
   -> test_rule_findings_are_never_served_from_cache
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from conftest import requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule
from inkloom_api.models import AuditEvent

CLAIM = "Lumen Pods offer up to 12 hours of playback per charge."
SUPPORTED = [
    ScriptedRule(
        "12 hours of playback per charge",
        "SUPPORTED",
        "up to 12 hours of playback per charge",
        "The fact sheet states 12 hours.",
    )
]
NOT_CHECKABLE = {
    "style.link_text",
    "style.alt_text",
    "style.headings",
    "style.media_captions",
    "style.contrast",
}


def _rule_findings(review: dict) -> list[dict]:
    return [f for f in review["findings"] if f["check_type"] == "rule"]


def _claim_status(review: dict, sentence: str) -> str:
    [finding] = [
        f
        for f in review["findings"]
        if f["check_type"] != "rule" and f["original_text"] == sentence
    ]
    return finding["verification_status"]


def _checks(review: dict) -> dict[str, dict]:
    return {c["rule_id"]: c for c in review["rule_checks"]}


def _put_rules(client, account, rules, brand_id: str | None = None):
    return client.put(
        f"/api/brands/{brand_id or account.brand_id}/rules",
        json={"rules": rules},
        headers=account.headers,
    )


@requires_db
def test_default_accessibility_checks_run_with_no_brand_rules(
    client, monkeypatch, account_factory
) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("owner")
    review = owner.submit(f"BUY NOW TODAY. {CLAIM}")

    [finding] = _rule_findings(review)
    assert finding["category"] == "accessibility" and finding["rule_id"] == "style.all_caps"
    assert finding["rule_type"] == "all_caps_run" and finding["scope"] == "text"
    assert (
        finding["verification_status"] == "not_applicable"
        and finding["requires_human_review"] is True
    )
    assert (
        review["text"][finding["span"]["start"] : finding["span"]["end"]]
        == finding["original_text"]
        == "BUY NOW TODAY"
    )
    assert finding["evidence"] == [] and finding["source_ids"] == []
    assert finding["suggested_correction"] is None and finding["suggestion_basis"] is None

    assert review["rules_status"] == "complete"
    checks = _checks(review)
    assert (
        checks["style.all_caps"]["status"] == "violated"
        and checks["style.all_caps"]["findings"] == 1
    )
    for rule_id in NOT_CHECKABLE:
        assert checks[rule_id]["status"] == "not_checkable" and checks[rule_id]["reason"], rule_id
    # The claim check ran as before, alongside the rule finding (the scripted extractor makes every
    # sentence a claim, so "BUY NOW TODAY." is a claim too).
    assert _claim_status(review, CLAIM) == "supported"
    assert review["status"] == "needs_human_review"
    assert client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json() == review


@requires_db
def test_clean_draft_completes_and_unchecked_is_not_passed(
    client, monkeypatch, account_factory
) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    review = account_factory("owner").submit(CLAIM)
    assert _rule_findings(review) == []
    assert review["status"] == "completed" and review["rules_status"] == "complete"
    statuses = {c["rule_id"]: c["status"] for c in review["rule_checks"]}
    assert {r for r, s in statuses.items() if s == "passed"} == {"style.all_caps", "style.emoji"}
    assert all(statuses[r] == "not_checkable" for r in NOT_CHECKABLE)


@requires_db
def test_brand_rules_api_and_terminology_finding(
    client, monkeypatch, db_session, account_factory
) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("owner")
    assert client.get(f"/api/brands/{owner.brand_id}/rules", headers=owner.headers).json() == {
        "brand_id": owner.brand_id,
        "rules": None,
    }

    rules = {
        "prohibited_terms": [
            {
                "rule_id": "no-guarantee",
                "term": "guaranteed",
                "approved_alternative": "designed",
                "severity": "high",
            }
        ]
    }
    saved = _put_rules(client, owner, rules)
    assert saved.status_code == 200, saved.text
    stored = saved.json()["rules"]
    assert stored["rule_set_id"] == f"brand-{owner.brand_id}" and stored["version"] == "1"
    assert (
        client.get(f"/api/brands/{owner.brand_id}/rules", headers=owner.headers).json()["rules"]
        == stored
    )

    review = owner.submit(f"Guaranteed comfort. {CLAIM}")
    [finding] = _rule_findings(review)
    assert (finding["category"], finding["rule_id"], finding["rule_type"]) == (
        "terminology",
        "no-guarantee",
        "prohibited_term",
    )
    assert finding["severity"] == "high" and finding["original_text"] == "Guaranteed"
    assert (
        finding["suggested_correction"] == "designed"
        and finding["suggestion_basis"] == "brand_rule"
    )
    assert _checks(review)["no-guarantee"]["status"] == "violated"

    assert _put_rules(client, owner, rules).json()["rules"]["version"] == "2"
    assert _put_rules(client, owner, {}).json()["rules"]["version"] == "3"  # empty: defaults only
    assert _put_rules(client, owner, None).json()["rules"] is None
    cleared = owner.submit(f"Guaranteed comfort. {CLAIM}")
    assert _rule_findings(cleared) == [] and "no-guarantee" not in _checks(cleared)

    db_session.expire_all()
    events = [
        e.event_type
        for e in db_session.query(AuditEvent)
        .filter(
            AuditEvent.organisation_id == uuid.UUID(owner.organisation_id),
            AuditEvent.event_type.like("brand.rules_%"),
        )
        .order_by(AuditEvent.created_at)
    ]
    assert events == ["brand.rules_updated"] * 3 + ["brand.rules_cleared"]


@requires_db
@pytest.mark.parametrize("quoted_from_approved_source", [True, False])
def test_rule_evidence_is_kept_only_if_it_is_really_in_an_approved_document(
    client, monkeypatch, account_factory, quoted_from_approved_source
) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("owner")
    doc_id = owner.source_id if quoted_from_approved_source else str(uuid.uuid4())
    rules = {
        "prohibited_terms": [
            {
                "rule_id": "no-lifetime",
                "term": "lifetime warranty",
                "approved_alternative": "2-year warranty",
                "source": {"doc_id": doc_id, "quote": "Warranty: 2 years."},
            }
        ]
    }
    assert _put_rules(client, owner, rules).status_code == 200

    review = owner.submit(f"Lumen Pods come with a lifetime warranty. {CLAIM}")
    [finding] = _rule_findings(review)
    if quoted_from_approved_source:
        [evidence] = finding["evidence"]
        assert (
            evidence["source_id"] == owner.source_id and evidence["quote"] == "Warranty: 2 years."
        )
        assert evidence["relation"] == "contradicts" and evidence["source_title"] == "Fact Sheet"
        assert finding["source_ids"] == [owner.source_id]
        assert (
            finding["suggested_correction"] == "2-year warranty"
            and finding["suggestion_basis"] == "approved_document"
        )
    else:
        # Not one of this brand's approved documents: no evidence, and no suggestion resting on it.
        assert finding["evidence"] == [] and finding["source_ids"] == []
        assert finding["suggested_correction"] is None and finding["suggestion_basis"] is None
        assert (
            finding["rule_id"] == "no-lifetime" and finding["original_text"] == "lifetime warranty"
        )


@requires_db
def test_invalid_rules_are_refused_when_saved(client, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    good = {"prohibited_terms": [{"rule_id": "no-guarantee", "term": "guaranteed"}]}
    assert _put_rules(client, owner, good).status_code == 200

    secret_term = "zebra-secret-term"
    for bad, expected in [
        (
            {
                "required_terms": [{"rule_id": "a", "term": secret_term}],
                "prohibited_terms": [{"rule_id": "b", "term": secret_term}],
            },
            "conflicting rules: a requires a term that b prohibits",
        ),
        ({"bogus_rules": []}, "bogus_rules"),
        ({"prohibited_terms": [{"rule_id": "bad id!", "term": "x"}]}, "prohibited_terms.0.rule_id"),
        ({"prohibited_terms": [{"rule_id": "n", "term": "a\x00b"}]}, "NUL"),
    ]:
        response = _put_rules(client, owner, bad)
        assert response.status_code == 422, response.text
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR" and expected in error["message"], error
        assert secret_term not in error["message"]
    assert _put_rules(client, owner, ["not", "an", "object"]).status_code == 422

    stored = client.get(f"/api/brands/{owner.brand_id}/rules", headers=owner.headers).json()[
        "rules"
    ]
    assert stored["version"] == "1" and stored["prohibited_terms"][0]["rule_id"] == "no-guarantee"


@requires_db
def test_other_accounts_rules_are_unreachable(client, account_factory) -> None:
    owner, other = (
        account_factory("owner", with_source=False),
        account_factory("other", with_source=False),
    )
    assert (
        _put_rules(client, owner, {"prohibited_terms": [{"rule_id": "x", "term": "y"}]}).status_code
        == 200
    )
    random_id = str(uuid.uuid4())
    for brand_id in (owner.brand_id, random_id):
        read = client.get(f"/api/brands/{brand_id}/rules", headers=other.headers)
        write = _put_rules(client, other, None, brand_id=brand_id)
        assert read.status_code == write.status_code == 404
        assert (
            read.json()["error"]["message"] == write.json()["error"]["message"] == "brand not found"
        )
    assert (
        client.get(f"/api/brands/{owner.brand_id}/rules", headers=owner.headers).json()["rules"][
            "version"
        ]
        == "1"
    )


@requires_db
def test_stored_rules_that_no_longer_validate_are_not_applied(
    client, monkeypatch, db_session, account_factory
) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("owner")
    # As if an engine upgrade made previously valid rules invalid: written straight to the column.
    db_session.execute(
        text("UPDATE brand_profiles SET rules = CAST(:r AS jsonb) WHERE id = :id"),
        {"r": '{"rule_set_id": "r", "unknown_rule_kind": []}', "id": owner.brand_id},
    )
    db_session.commit()

    review = owner.submit(f"BUY NOW TODAY. {CLAIM}")
    assert review["rules_status"] == "not_applied" and review["rule_checks"] is None
    assert _rule_findings(review) == []  # nothing is made up - not even the default checks
    assert review["error_summary"].startswith("Brand rules could not be applied: unknown_rule_kind")
    assert _claim_status(review, CLAIM) == "supported"  # claims still checked
    assert review["status"] == "needs_human_review"


@requires_db
def test_rules_engine_crash_fabricates_nothing(client, monkeypatch, account_factory) -> None:
    from inkloom_api.engine import brand_rules

    use_scripted_provider(monkeypatch, SUPPORTED)

    def crash(*args, **kwargs):
        raise RuntimeError("rules engine bug")

    monkeypatch.setattr(brand_rules, "evaluate_rules", crash)
    review = account_factory("owner").submit(f"BUY NOW TODAY. {CLAIM}")
    assert review["rules_status"] == "not_applied" and review["rule_checks"] is None
    assert _rule_findings(review) == []
    assert (
        "failed unexpectedly (RuntimeError)" in review["error_summary"]
        and "rules engine bug" not in review["error_summary"]
    )
    assert _claim_status(review, CLAIM) == "supported"
    assert review["status"] == "needs_human_review"


@requires_db
def test_a_check_that_errors_makes_the_rules_incomplete(
    client, monkeypatch, account_factory
) -> None:
    from inkloom_verify.schemas import (
        RuleCategory,
        RuleCheck,
        RuleCheckStatus,
        RuleEvaluation,
        RuleType,
    )

    from inkloom_api.engine import brand_rules

    use_scripted_provider(monkeypatch, SUPPORTED)
    errored = RuleEvaluation(
        findings=[],
        complete=False,
        checks=[
            RuleCheck(
                rule_id="style.all_caps",
                rule_type=RuleType.ALL_CAPS_RUN,
                category=RuleCategory.ACCESSIBILITY,
                status=RuleCheckStatus.ERROR,
                reason="RuntimeError",
            )
        ],
    )
    monkeypatch.setattr(brand_rules, "evaluate_rules", lambda *args, **kwargs: errored)

    review = account_factory("owner").submit(CLAIM)  # a clean, supported claim...
    assert review["rules_status"] == "incomplete"
    assert review["rule_checks"] == [
        {
            "rule_id": "style.all_caps",
            "rule_type": "all_caps_run",
            "category": "accessibility",
            "status": "error",
            "findings": 0,
            "reason": "RuntimeError",
        }
    ]
    assert review["status"] == "needs_human_review"  # ...still isn't shown as clean
    assert "not shown as rule-clean" in review["error_summary"]


@requires_db
def test_rules_run_without_a_provider_and_without_sources(
    client, force_stub_mode, account_factory
) -> None:
    stub = account_factory("stub").submit(f"BUY NOW TODAY. {CLAIM}")
    assert {f["category"] for f in stub["findings"]} == {"stub", "accessibility"}
    assert stub["rules_status"] == "complete" and stub["status"] == "needs_human_review"

    no_sources = account_factory("empty", with_source=False).submit(f"BUY NOW TODAY. {CLAIM}")
    assert no_sources["status"] == "failed"  # the claims had nothing to be checked against
    assert [f["rule_id"] for f in no_sources["findings"]] == ["style.all_caps"]
    assert (
        no_sources["error_summary"]
        == "This brand has no approved sources to verify content against."
    )


@requires_db
def test_rule_findings_are_never_served_from_cache(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, SUPPORTED)
    owner = account_factory("owner")
    draft = f"BUY NOW TODAY. {CLAIM}"
    first = owner.submit(draft)
    second = owner.submit(draft)
    assert first["served_from_cache"] is False and second["served_from_cache"] is True
    assert [f["rule_id"] for f in _rule_findings(second)] == [
        "style.all_caps"
    ]  # once, not duplicated
    assert len(second["findings"]) == len(first["findings"])

    # The rules change, the content and its sources don't: the claims are still cached, the
    # rule findings follow the new rules.
    _put_rules(client, owner, {"prohibited_terms": [{"rule_id": "no-buy-now", "term": "buy now"}]})
    third = owner.submit(draft)
    assert third["served_from_cache"] is True
    assert sorted(f["rule_id"] for f in _rule_findings(third)) == ["no-buy-now", "style.all_caps"]
