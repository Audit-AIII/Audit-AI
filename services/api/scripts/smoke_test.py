"""Smoke test against a REAL running server, over real HTTP, as a brand-new individual user.

    register -> upload an approved brand document -> submit a review -> list reviews ->
    fetch the review -> analytics -> latest evaluation (404 before any run)

then, if the review reached a decidable state, approves it ("ready to publish") and checks the
content history. Needs no seed data and no database access: every id comes from the responses.

With an AI provider configured (services/api/.env) the review is real; without one it is the
clearly labelled stub (category "stub") and the script says so. Free-tier providers can fail a
single review (status "failed"); that is reported, not hidden.

Env vars (all optional):
  BASE_URL   default http://localhost:8000

Run (server already running: .venv/Scripts/python -m uvicorn inkloom_api.main:app):
  .venv/Scripts/python scripts/smoke_test.py
"""

from __future__ import annotations

import os
import sys
import uuid

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
FACT_SHEET = (
    "Lumen Pods - Product Fact Sheet\n\n"
    "Battery life: up to 12 hours of playback per charge; up to 36 hours with the charging case.\n"
    "Water resistance: IPX4 (splash resistant). Not suitable for swimming.\n"
    "Warranty: 2 years.\n"
)
DRAFT = (
    "Lumen Pods offer up to 24 hours of playback per charge. "
    "Lumen Pods are India's number one earbuds. Lumen Pods come with a 2-year warranty."
)
REVIEW_KEYS = {
    "id",
    "content_version_id",
    "content_item_id",
    "brand_id",
    "brand_name",
    "title",
    "status",
    "findings",
}
RISK_KEYS = {
    "top_categories",
    "median_turnaround_minutes",
    "re_review_rate",
    "queue_age_minutes",
    "sample_size",
}


def step(label: str) -> None:
    print(f"\n== {label} ==")


def fail(message: str) -> None:
    print(f"SMOKE TEST FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def expect(response: httpx.Response, status: int, what: str) -> dict | list:
    if response.status_code != status:
        fail(f"{what}: expected {status}, got {response.status_code} {response.text[:300]}")
    return response.json()


def main() -> None:
    client = httpx.Client(base_url=BASE_URL, timeout=180.0)

    step("register")
    email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
    body = expect(
        client.post(
            "/api/auth/register", json={"email": email, "password": "correct-horse-battery"}
        ),
        201,
        "register",
    )
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    brand_id = body["brand"]["id"]
    print(f"  {email}: role={body['role']} (account owner), starter brand {brand_id}")

    step("upload an approved brand document")
    source = expect(
        client.post(
            f"/api/brands/{brand_id}/sources",
            data={"title": "Fact Sheet", "approve": "true"},
            files={"file": ("facts.txt", FACT_SHEET.encode(), "text/plain")},
            headers=headers,
        ),
        201,
        "upload source",
    )
    print(f"  source {source['id']} status={source['status']}")

    step("submit a review")
    review = expect(
        client.post(
            "/api/reviews",
            json={"brand_id": brand_id, "text": DRAFT, "title": "Smoke draft"},
            headers=headers,
        ),
        201,
        "POST /api/reviews",
    )
    missing = REVIEW_KEYS - set(review)
    if missing:
        fail(f"review response missing {sorted(missing)}")
    stub = any(f["category"] == "stub" for f in review["findings"])
    print(
        f"  review {review['id']} status={review['status']} engine={review['engine']} "
        f"required_reviewer_role={review['required_reviewer_role']}"
    )
    if stub:
        print(
            "  NOTE: stub output - no AI provider configured; findings are a labelled placeholder."
        )
    for finding in review["findings"]:
        print(
            f"   - [{finding['verification_status']}/{finding['category']}] {finding['original_text']!r}"
            + (
                f" -> suggest {finding['suggested_correction']!r}"
                if finding["suggested_correction"]
                else ""
            )
        )
        for evidence in finding["evidence"]:
            print(
                f"       {evidence['relation']}: {evidence['quote']!r} "
                f"({evidence['source_title']} v{evidence['source_version_number']})"
            )
    # Round 3 routing (risk_policy.py): every finished check is routed to a reviewer or straight
    # to an approver; a solo owner can still approve (decision D1 / DECISIONS_PENDING.md P4).
    if review["required_reviewer_role"] not in ("reviewer", "approver"):
        fail(f"routing: unexpected required_reviewer_role {review['required_reviewer_role']!r}")
    if review["workflow_status"] != "draft" or "approve" not in review["allowed_actions"]:
        fail(f"workflow: {review['workflow_status']} / {review['allowed_actions']}")
    print(
        f"  routing: risk={review['risk_level']} -> {review['required_reviewer_role']} "
        f"({review['routing_reason']['code']}); approval_mode={review['approval_mode']}"
    )

    step("list reviews")
    listed = expect(client.get("/api/reviews", headers=headers), 200, "GET /api/reviews")
    if not isinstance(listed, list) or [r["id"] for r in listed] != [review["id"]]:
        fail(f"expected a plain array holding exactly this review, got {listed!r:.300}")
    status = review["status"]
    print(
        f"  {len(listed)} review(s); ?status={status} -> "
        f"{len(expect(client.get(f'/api/reviews?status={status}', headers=headers), 200, 'filter'))}"
    )

    step("fetch the review")
    fetched = expect(
        client.get(f"/api/reviews/{review['id']}", headers=headers), 200, "GET /api/reviews/{id}"
    )
    if fetched != listed[0]:
        fail("GET /api/reviews/{id} differs from the list entry")
    print(
        f"  brand_name={fetched['brand_name']!r} title={fetched['title']!r} version={fetched['version_number']}"
    )

    step("brand dashboard + analytics")
    [brand] = expect(client.get("/api/brands", headers=headers), 200, "GET /api/brands")
    print(
        f"  review_count={brand['review_count']} open_review_count={brand['open_review_count']} "
        f"last_review_at={brand['last_review_at']}"
    )
    risk = expect(
        client.get(f"/api/analytics/brand-risk?brand_id={brand_id}", headers=headers),
        200,
        "brand-risk",
    )
    if not RISK_KEYS <= set(risk):  # fields are additive: check the required ones are there
        fail(f"brand-risk is missing {sorted(RISK_KEYS - set(risk))}")
    print(f"  {risk}")

    step("latest evaluation (none run yet)")
    latest = client.get("/api/evaluations/latest", headers=headers)
    expect(latest, 404, "GET /api/evaluations/latest before any run")
    print(f"  404 {latest.json()['error']['message']!r}")

    if review["status"] in ("completed", "needs_human_review"):
        step("approve (ready to publish) + history")
        event = expect(
            client.post(
                f"/api/content-versions/{review['content_version_id']}/approve", headers=headers
            ),
            201,
            "approve",
        )
        history = expect(
            client.get(f"/api/content/{review['content_item_id']}/history", headers=headers),
            200,
            "history",
        )
        print(
            f"  {event['action']}; history decisions={[d['action'] for v in history['versions'] for d in v['decisions']]}"
        )
    else:
        print(
            f"\n  review status {review['status']!r} is not decidable (error: {review['error_summary']!r}); "
            "skipped approve. Retry if this was a provider hiccup."
        )

    print("\nSMOKE TEST PASSED" + (" (stub mode)" if stub else ""))


if __name__ == "__main__":
    main()
