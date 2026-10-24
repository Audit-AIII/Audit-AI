"""GET /api/analytics/brand-risk - the Insights page (step 6). Shape must match analytics.ts's
BrandRisk exactly; every number comes from real rows in the period, never invented.

1. zero reviews -> 200, empty list, nulls, sample_size 0;
   -> test_zero_reviews_returns_empty_and_nulls
2. real numbers with pinned timestamps: categories (stub/supported excluded), median turnaround to
   first decision, re-review rate, queue age of reviews waiting for a decision; the period filter;
   -> test_metrics_from_real_rows_and_period
3. top_categories is capped at 6, sorted by count;
   -> test_top_categories_capped_at_six
4. stub findings never count as a category;
   -> test_stub_findings_are_not_a_category
5. another account's brand (or a random one) -> the same 404; bad days -> 422; needs a token.
   -> test_other_accounts_brand_is_404_and_validation
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from conftest import requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule
from inkloom_api.models import Finding

RULES = [
    ScriptedRule(
        "24 hours", "CONTRADICTED", "up to 12 hours of playback per charge", "12, not 24."
    ),
    ScriptedRule("number one", "NOT_ENOUGH_EVIDENCE", None, "No rankings in any document."),
    ScriptedRule("warranty", "SUPPORTED", "Warranty: 2 years.", "Stated."),
]
EXPECTED_KEYS = {
    "top_categories",
    "median_turnaround_minutes",
    "re_review_rate",
    "queue_age_minutes",
    "sample_size",
    "dismissed_finding_rate",
}


def _risk(client, account, query: str = ""):
    return client.get(
        f"/api/analytics/brand-risk?brand_id={account.brand_id}{query}", headers=account.headers
    )


def _set_created(db_session, table: str, row_id: str, when: datetime, column: str = "id") -> None:
    db_session.execute(
        text(f"UPDATE {table} SET created_at = :when WHERE {column} = :id"),
        {"when": when, "id": row_id},
    )
    db_session.commit()


@requires_db
def test_zero_reviews_returns_empty_and_nulls(client, account_factory) -> None:
    owner = account_factory("owner")
    response = _risk(client, owner)
    assert response.status_code == 200
    assert response.json() == {
        "top_categories": [],
        "median_turnaround_minutes": None,
        "re_review_rate": None,
        "queue_age_minutes": {"median": None, "oldest": None},
        "sample_size": 0,
        "dismissed_finding_rate": {"numerator": 0, "denominator": 0, "value": None},
    }


@requires_db
def test_metrics_from_real_rows_and_period(
    client, monkeypatch, db_session, account_factory
) -> None:
    use_scripted_provider(monkeypatch, RULES)
    owner, other = account_factory("owner"), account_factory("other")
    other.submit("Lumen Pods offer up to 24 hours of playback per charge.")  # never counted
    now = datetime.now(timezone.utc)

    # Decided 120 minutes after it was created: contradicted + unsupported.
    decided = owner.submit(
        "Lumen Pods offer up to 24 hours of playback per charge. They are India's number one earbuds."
    )
    event = client.post(
        f"/api/content-versions/{decided['content_version_id']}/approve", headers=owner.headers
    ).json()
    _set_created(db_session, "reviews", decided["id"], now - timedelta(minutes=180))
    _set_created(db_session, "approval_events", event["id"], now - timedelta(minutes=60))

    # Waiting for 120 minutes: unsupported.
    waiting = owner.submit("Lumen Pods are India's number one earbuds.")
    _set_created(db_session, "reviews", waiting["id"], now - timedelta(minutes=120))

    # One item, two versions: v1's review is stale (not waiting), v2's waits 30 minutes. Supported only.
    v1 = owner.submit("Lumen Pods come with a 2-year warranty.")
    v2 = client.post(
        f"/api/content/{v1['content_item_id']}/versions",
        json={"text": "Every pair of Lumen Pods comes with a 2-year warranty."},
        headers=owner.headers,
    ).json()
    _set_created(db_session, "reviews", v1["id"], now - timedelta(minutes=50))
    _set_created(db_session, "reviews", v2["review"]["id"], now - timedelta(minutes=30))

    # Outside a 30-day period.
    old = owner.submit("Lumen Pods are the number one choice.")
    _set_created(db_session, "reviews", old["id"], now - timedelta(days=40))

    body = _risk(client, owner).json()
    assert set(body) == EXPECTED_KEYS
    assert body["sample_size"] == 4
    assert body["top_categories"] == [
        {"category": "unsupported_claim", "count": 2},
        {"category": "contradicted_claim", "count": 1},
    ]  # supported_claim excluded
    assert body["median_turnaround_minutes"] == pytest.approx(120.0, abs=0.2)
    assert body["re_review_rate"] == pytest.approx(1 / 3, abs=1e-3)  # 1 of 3 items has 2+ versions
    assert body["queue_age_minutes"]["median"] == pytest.approx(75.0, abs=1.0)  # (120 + 30) / 2
    assert body["queue_age_minutes"]["oldest"] == pytest.approx(120.0, abs=1.0)

    wider = _risk(client, owner, "&days=60").json()
    assert wider["sample_size"] == 5
    assert {"category": "unsupported_claim", "count": 3} in wider["top_categories"]
    assert wider["queue_age_minutes"]["oldest"] == pytest.approx(40 * 24 * 60, abs=2.0)


@requires_db
def test_top_categories_capped_at_six(client, force_stub_mode, db_session, account_factory) -> None:
    owner = account_factory("owner")
    review = owner.submit()
    for index, category in enumerate(["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"]):
        for _ in range(8 - index):  # c1 most frequent ... c8 least
            db_session.add(
                Finding(
                    review_id=uuid.UUID(review["id"]),
                    category=category,
                    severity="medium",
                    original_text="x",
                    span_start=0,
                    span_end=1,
                    check_type="retrieval",
                    verification_status="unverified",
                )
            )
    db_session.commit()

    categories = _risk(client, owner).json()["top_categories"]
    assert [c["category"] for c in categories] == ["c1", "c2", "c3", "c4", "c5", "c6"]
    assert [c["count"] for c in categories] == [8, 7, 6, 5, 4, 3]


@requires_db
def test_stub_findings_are_not_a_category(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner")
    owner.submit()
    body = _risk(client, owner).json()
    assert body["sample_size"] == 1
    assert body["top_categories"] == []


@requires_db
def test_other_accounts_brand_is_404_and_validation(
    client, force_stub_mode, account_factory
) -> None:
    owner, other = account_factory("owner"), account_factory("other")
    other.submit()
    theirs = client.get(
        f"/api/analytics/brand-risk?brand_id={other.brand_id}", headers=owner.headers
    )
    random_brand = client.get(
        f"/api/analytics/brand-risk?brand_id={uuid.uuid4()}", headers=owner.headers
    )
    assert theirs.status_code == random_brand.status_code == 404
    assert theirs.json()["error"]["message"] == random_brand.json()["error"]["message"]
    for bad in ("&days=0", "&days=366", "&days=abc"):
        assert _risk(client, owner, bad).status_code == 422, bad
    assert client.get(f"/api/analytics/brand-risk?brand_id={owner.brand_id}").status_code == 401
