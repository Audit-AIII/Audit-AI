"""Phase 8 task 3: smoke test against a REAL running server and real engine, over real HTTP.

Exercises exactly the path phase8_tests_seed_readme_deploy.md task 3 asks for: create review,
fetch findings, request changes, create new version, approve, inspect audit. Run this against
`uvicorn inkloom_api.main:app` already running, after `scripts/seed.py` (for a brand with real
approved sources and a known login - it prints the BRAND_ID this script needs).

One known pre-existing contract gap, found while writing this rather than guessed: `ReviewOut`
(what `POST /api/reviews` and `GET /api/reviews/{id}` return) never carries `content_item_id` -
only `content_version_id`. `POST /api/content/{content_item_id}/versions` (the "create new
version" step) needs the content item id, which no response in this flow exposes. The test
suite already hits the same wall (see `test_approval_rejected_when_stale` in
tests/test_content_versioning.py, "the review response doesn't expose it, so fetch it through
the DB directly") - this script does the same, documented, workaround rather than quietly
inventing a new route. Flagging this as a real contract question for the team, not fixing it
here per 00_CONTEXT.md ("If the contract must change, propose it... and wait").

Because the configured LLM providers are free tiers (documented limitation - see
DISCLOSURE.md/STATUS.md), a single review can land in `failed` rather than a decidable state
from provider flakiness alone, not a bug in this script. Each submission step retries a few
times before giving up.

Env vars (all optional except BRAND_ID):
  BASE_URL      default http://localhost:8000
  EMAIL         default admin@seed.inkloom.demo (the seeded admin: holds every permission)
  PASSWORD      default the seed script's DEMO_PASSWORD
  BRAND_ID      required - run scripts/seed.py first, it prints this
  DATABASE_URL  required for the one content_item_id lookup above (same as the seed script)

Run:
  BRAND_ID=<id> DATABASE_URL=... .venv/Scripts/python scripts/smoke_test.py
"""

from __future__ import annotations

import os
import sys
import uuid

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
EMAIL = os.environ.get("EMAIL", "admin@seed.inkloom.demo")
PASSWORD = os.environ.get("PASSWORD", "SeedDemo!2026-not-a-real-secret")
BRAND_ID = os.environ.get("BRAND_ID")
MAX_SUBMIT_ATTEMPTS = 3
DECIDABLE = {"completed", "needs_human_review"}


def _step(label: str) -> None:
    print(f"\n== {label} ==")


def fail(message: str) -> None:
    print(f"SMOKE TEST FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def _content_item_id(content_version_id: str) -> str:
    """The documented workaround (see module docstring) - a direct DB lookup for the one id
    this API's responses never expose."""
    from inkloom_api.db import get_session_factory
    from inkloom_api.models import ContentVersion

    db = get_session_factory()()
    try:
        version = db.get(ContentVersion, uuid.UUID(content_version_id))
        if version is None:
            fail(f"content_version {content_version_id} not found in the database")
        return str(version.content_item_id)
    finally:
        db.close()


def main() -> None:
    if not BRAND_ID:
        fail("BRAND_ID is required - run scripts/seed.py first and pass the BRAND_ID it prints.")

    client = httpx.Client(base_url=BASE_URL, timeout=60.0)

    _step("login")
    login = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if login.status_code != 200:
        fail(f"login failed: {login.status_code} {login.text}")
    login_body = login.json()
    headers = {"Authorization": f"Bearer {login_body['access_token']}"}
    print(f"logged in as {EMAIL}, role={login_body['role']}")

    _step("create review")
    review = None
    for attempt in range(1, MAX_SUBMIT_ATTEMPTS + 1):
        text = f"Lumen Pods offer up to 12 hours of playback per charge. (smoke test attempt {attempt})"
        response = client.post("/api/reviews", json={"brand_id": BRAND_ID, "text": text}, headers=headers)
        if response.status_code != 201:
            fail(f"POST /api/reviews failed: {response.status_code} {response.text}")
        review = response.json()
        print(f"  attempt {attempt}: review {review['id']} -> status={review['status']}")
        if review["status"] in DECIDABLE:
            break
    else:
        fail(
            f"no review reached a decidable state {DECIDABLE} in {MAX_SUBMIT_ATTEMPTS} attempts - "
            "likely free-tier provider flakiness (a documented limitation, not this script). Retry, "
            "or configure a local Ollama model for a reliable fallback."
        )
    assert review is not None

    _step("fetch findings")
    fetched = client.get(f"/api/reviews/{review['id']}", headers=headers)
    if fetched.status_code != 200:
        fail(f"GET /api/reviews/{{id}} failed: {fetched.status_code} {fetched.text}")
    print(f"  {len(fetched.json().get('findings', []))} finding(s)")

    content_version_id = review["content_version_id"]
    content_item_id = _content_item_id(content_version_id)

    _step("request changes")
    request_changes = client.post(
        f"/api/content-versions/{content_version_id}/request-changes",
        json={"decision": "changes_requested", "note": "smoke test: please revise"},
        headers=headers,
    )
    if request_changes.status_code != 201:
        fail(f"request-changes failed: {request_changes.status_code} {request_changes.text}")
    print(f"  decision recorded: {request_changes.json()['action']}")

    _step("create new version")
    new_version = None
    for attempt in range(1, MAX_SUBMIT_ATTEMPTS + 1):
        response = client.post(
            f"/api/content/{content_item_id}/versions",
            json={"text": f"Lumen Pods offer up to 12 hours of playback per charge. Revised per feedback (attempt {attempt})."},
            headers=headers,
        )
        if response.status_code != 201:
            fail(f"create new version failed: {response.status_code} {response.text}")
        new_version = response.json()
        print(f"  attempt {attempt}: version {new_version['content_version_id']} -> review status={new_version['review']['status']}")
        if new_version["review"]["status"] in DECIDABLE:
            break
    else:
        fail(f"new version's review never reached a decidable state {DECIDABLE} - same free-tier caveat as above.")
    assert new_version is not None

    _step("approve")
    approve = client.post(f"/api/content-versions/{new_version['content_version_id']}/approve", headers=headers)
    if approve.status_code != 201:
        fail(f"approve failed: {approve.status_code} {approve.text}")
    print(f"  approved: action={approve.json()['action']}")

    _step("inspect audit (content history)")
    history = client.get(f"/api/content/{content_item_id}/history", headers=headers)
    if history.status_code != 200:
        fail(f"GET history failed: {history.status_code} {history.text}")
    versions = history.json()["versions"]
    print(f"  {len(versions)} version(s) in history")
    for v in versions:
        decisions = [d["action"] for d in v["decisions"]]
        print(f"    v{v['version_number']} is_current={v['is_current']} decisions={decisions}")

    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main()
