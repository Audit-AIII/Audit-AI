"""Plan step 7 leftovers.

1. GET /api/analytics/brand-risk gains dismissed_finding_rate: of the period's flagged findings
   (every category but stub and supported_claim), how many are dismissed now - latest decision
   only, so dismissed-then-restored doesn't count; value null when nothing is flagged; scoped to
   the brand; existing fields unchanged;
   -> test_dismissed_finding_rate_exact_values
   -> test_dismissed_finding_rate_is_null_with_nothing_flagged
2. a hand-written new version that drops a locked phrase is saved, with a warning listing it
   (warn, never block); keeping every lock gives no warning.
   -> test_new_version_warns_about_dropped_locked_phrases
"""

from __future__ import annotations

from conftest import requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule

DRAFT = (
    "Lumen Pods offer up to 24 hours of playback per charge. "
    "Lumen Pods are India's number one earbuds. "
    "Lumen Pods come with a 2 year warranty."
)
RULES = [
    ScriptedRule(
        "24 hours of playback per charge",
        "CONTRADICTED",
        "up to 12 hours of playback per charge",
        "12 hours.",
    ),
    ScriptedRule("number one", "NOT_ENOUGH_EVIDENCE", None, "No rankings."),
    ScriptedRule("warranty", "SUPPORTED", "Warranty: 2 years.", "2 years."),
]


def _risk(client, account, brand_id=None) -> dict:
    response = client.get(
        f"/api/analytics/brand-risk?brand_id={brand_id or account.brand_id}",
        headers=account.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


@requires_db
def test_dismissed_finding_rate_exact_values(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, RULES)
    owner = account_factory("owner")
    review = owner.submit(DRAFT)
    by_category = {f["category"]: f["finding_id"] for f in review["findings"]}
    assert set(by_category) == {"contradicted_claim", "unsupported_claim", "supported_claim"}
    before = _risk(client, owner)
    assert before["dismissed_finding_rate"] == {"numerator": 0, "denominator": 2, "value": 0.0}

    dismiss = lambda fid: client.post(f"/api/findings/{fid}/dismiss", headers=owner.headers)  # noqa: E731
    assert dismiss(by_category["contradicted_claim"]).status_code == 201
    assert dismiss(by_category["unsupported_claim"]).status_code == 201
    assert (
        client.post(
            f"/api/findings/{by_category['unsupported_claim']}/restore", headers=owner.headers
        ).status_code
        == 201
    )
    assert (
        dismiss(by_category["supported_claim"]).status_code == 201
    )  # not a flagged finding: not counted

    after = _risk(client, owner)
    assert after["dismissed_finding_rate"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    # Existing fields are unchanged by dismissing.
    assert {k: v for k, v in after.items() if k != "dismissed_finding_rate"} == {
        k: v for k, v in before.items() if k != "dismissed_finding_rate"
    }

    # Scoped to the brand: another brand of the same account has nothing flagged.
    other_brand = owner.create_brand("Other brand")["id"]
    assert _risk(client, owner, other_brand)["dismissed_finding_rate"] == {
        "numerator": 0,
        "denominator": 0,
        "value": None,
    }


@requires_db
def test_dismissed_finding_rate_is_null_with_nothing_flagged(
    client, force_stub_mode, account_factory
) -> None:
    owner = account_factory("owner")
    assert _risk(client, owner)["dismissed_finding_rate"] == {
        "numerator": 0,
        "denominator": 0,
        "value": None,
    }
    stub = owner.submit()["findings"][0]
    assert stub["category"] == "stub"
    assert (
        client.post(
            f"/api/findings/{stub['finding_id']}/dismiss", headers=owner.headers
        ).status_code
        == 201
    )
    assert _risk(client, owner)["dismissed_finding_rate"] == {
        "numerator": 0,
        "denominator": 0,
        "value": None,
    }


@requires_db
def test_new_version_warns_about_dropped_locked_phrases(
    client, force_stub_mode, db_session, account_factory
) -> None:
    owner = account_factory("owner")
    v1 = owner.submit("Lumen Pods cost ₹2,499. Buy Lumen Pods ₹2,499 today.")
    assert (
        client.put(
            f"/api/content-versions/{v1['content_version_id']}/locks",
            headers=owner.headers,
            json={"locked_phrases": ["₹2,499", "Lumen Pods"]},
        ).status_code
        == 200
    )

    url = f"/api/content/{v1['content_item_id']}/versions"
    dropped = client.post(
        url, json={"text": "Lumen Pods cost ₹2,499. Buy them today."}, headers=owner.headers
    )
    assert dropped.status_code == 201, dropped.text  # warned, not blocked
    body = dropped.json()
    assert body["is_current"] is True and body["version_number"] == 2
    assert body["lock_warnings"] == [
        {"phrase": "₹2,499", "occurrences_before": 2, "occurrences_after": 1},
        {"phrase": "Lumen Pods", "occurrences_before": 2, "occurrences_after": 1},
    ]
    assert body["review"]["locked_phrases"] == [
        "₹2,499",
        "Lumen Pods",
    ]  # the locks still carry over

    kept = client.post(
        url,
        json={"text": "Lumen Pods cost ₹2,499. Buy Lumen Pods at ₹2,499 now."},
        headers=owner.headers,
    )
    assert kept.status_code == 201 and kept.json()["lock_warnings"] == []
