"""Calls EVERY route the server publishes, over real HTTP, and fails if one was missed.

The route list comes from the server's own /openapi.json, so a new route without a check here fails
the run. Each route is called as the right person for its success case, and the riskier ones are also
called as someone who must be refused: no token, another workspace, or too small a role.

Needs a running server with no AI keys and raised rate limits (see e2e/README.md in the frontend).
POST /api/evaluations is only called if reviews come back as the stub, so this can't spend provider
quota. Creates throwaway check-*@example.com accounts. Never point it at a real database.

Run:  .venv/Scripts/python scripts/check_endpoints.py
Env:  BASE_URL (default http://localhost:8000)
"""

# ruff: noqa: E501
from __future__ import annotations

import os
import re
import sys
import uuid

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
PASSWORD = "check-endpoints-" + uuid.uuid4().hex[:8]
client = httpx.Client(base_url=BASE_URL, timeout=120)
called: set[tuple[str, str]] = set()
failures: list[str] = []
passed = 0


def call(person, method: str, template: str, expect, *, path=None, note: str = "", **kwargs):
    """One request. `template` is the OpenAPI path, recorded for the coverage check."""
    global passed
    called.add((method.upper(), template))
    url = template
    for key, value in (path or {}).items():
        url = url.replace("{" + key + "}", str(value))
    headers = dict(kwargs.pop("headers", {}))
    if person:
        headers["Authorization"] = f"Bearer {person['access_token']}"
    res = client.request(method, url, headers=headers, **kwargs)
    expected = expect if isinstance(expect, (set, tuple, list)) else {expect}
    who = person["_label"] if person else "no token"
    line = f"{method.upper():6} {template:58} {who:10} -> {res.status_code}{'  ' + note if note else ''}"
    if res.status_code in expected:
        passed += 1
        print(f"ok    {line}")
    else:
        failures.append(f"{line} (expected {sorted(expected)}): {res.text[:200]}")
        print(f"FAIL  {line} expected {sorted(expected)}: {res.text[:200]}")
    if res.status_code >= 500:
        failures.append(f"server error: {line}")
    try:
        return res.json()
    except ValueError:
        return None


def require(condition, message: str):
    global passed
    if condition:
        passed += 1
    else:
        failures.append(message)
        print(f"FAIL  {message}")


def code(body) -> str | None:
    return ((body or {}).get("error") or {}).get("code") if isinstance(body, dict) else None


def register(label: str):
    email = f"check-{label}-{uuid.uuid4().hex[:10]}@example.com"
    body = call(
        None,
        "POST",
        "/api/auth/register",
        201,
        json={"email": email, "password": PASSWORD, "display_name": label.title()},
    )
    body["_label"] = label
    body["_email"] = email
    return body


def upload(person, brand_id, approve=True, title="Spec"):
    return call(
        person,
        "POST",
        "/api/brands/{brand_id}/sources",
        201,
        path={"brand_id": brand_id},
        files={"file": ("spec.txt", b"The Lumen Pods last 24 hours on one charge.", "text/plain")},
        data={"title": title, "sensitivity": "normal", "approve": "true" if approve else "false"},
    )


def new_review(person, brand_id, title):
    return call(
        person,
        "POST",
        "/api/reviews",
        201,
        json={"brand_id": brand_id, "title": title, "text": "The Lumen Pods last 30 hours on one charge."},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )


def join(owner, label: str, role: str):
    """A teammate: invited, registered, accepted. Answers their session in the team workspace."""
    person = register(label)
    invite = call(
        owner,
        "POST",
        "/api/workspace/invitations",
        201,
        json={"email": person["_email"], "role": role},
    )
    session = call(person, "POST", "/api/invitations/accept", 200, json={"token": invite["token"]})
    session["_label"] = label
    session["_email"] = person["_email"]
    return session, person


def main() -> int:
    routes = {
        (method.upper(), path)
        for path, item in client.get("/openapi.json").json()["paths"].items()
        for method in item
    }
    print(f"The server publishes {len(routes)} routes.\n")

    call(None, "GET", "/health", 200)

    # --- Accounts --------------------------------------------------------------------------
    owner = register("owner")
    outsider = register("outsider")
    call(None, "POST", "/api/auth/register", 409, note="duplicate email", json={"email": owner["_email"], "password": PASSWORD})
    call(None, "POST", "/api/auth/login", 200, json={"email": owner["_email"], "password": PASSWORD})
    call(None, "POST", "/api/auth/login", 401, note="wrong password", json={"email": owner["_email"], "password": "wrong-password"})
    me = call(owner, "GET", "/api/auth/me", 200)
    require(me.get("memberships_count") == 1, f"/me memberships_count: {me.get('memberships_count')}")
    require(me.get("workspace", {}).get("member_count") == 1, f"/me workspace.member_count: {me.get('workspace')}")
    call(None, "GET", "/api/auth/me", 401)

    # --- Brands, documents, rules ----------------------------------------------------------
    brands = call(owner, "GET", "/api/brands", 200)
    brand_id = brands[0]["id"]
    created = call(owner, "POST", "/api/brands", 201, json={"name": "Second brand"})
    require(created["name"] == "Second brand", "brand name")
    call(None, "GET", "/api/brands", 401)

    source = upload(owner, brand_id)
    call(owner, "GET", "/api/brands/{brand_id}/sources", 200, path={"brand_id": brand_id})
    call(outsider, "GET", "/api/brands/{brand_id}/sources", 404, note="other workspace", path={"brand_id": brand_id})

    draft_doc = upload(owner, brand_id, approve=False, title="Draft doc")
    call(owner, "POST", "/api/brands/{brand_id}/sources/{source_id}/approve", 200, path={"brand_id": brand_id, "source_id": draft_doc["id"]})
    call(
        owner,
        "POST",
        "/api/brands/{brand_id}/sources/{source_id}/versions",
        201,
        path={"brand_id": brand_id, "source_id": draft_doc["id"]},
        files={"file": ("spec2.txt", b"The Lumen Pods last 26 hours on one charge.", "text/plain")},
    )
    call(
        owner,
        "POST",
        "/api/brands/{brand_id}/sources/{source_id}/withdraw",
        200,
        path={"brand_id": brand_id, "source_id": draft_doc["id"]},
        json={"status": "archived", "reason": "Replaced"},
    )
    removable = upload(owner, brand_id, approve=False, title="Remove me")
    call(owner, "DELETE", "/api/brands/{brand_id}/sources/{source_id}", 200, path={"brand_id": brand_id, "source_id": removable["id"]})
    call(outsider, "DELETE", "/api/brands/{brand_id}/sources/{source_id}", 404, note="other workspace", path={"brand_id": brand_id, "source_id": source["id"]})

    call(owner, "GET", "/api/brands/{brand_id}/rules", 200, path={"brand_id": brand_id})
    saved = call(
        owner,
        "PUT",
        "/api/brands/{brand_id}/rules",
        200,
        path={"brand_id": brand_id},
        json={"rules": {"prohibited_terms": [{"rule_id": "no-guarantee", "term": "guaranteed"}]}},
    )
    require(saved.get("rules"), "rules saved")
    call(outsider, "PUT", "/api/brands/{brand_id}/rules", 404, note="other workspace", path={"brand_id": brand_id}, json={"rules": None})

    # --- Reviews ---------------------------------------------------------------------------
    key = uuid.uuid4().hex
    body = {"brand_id": brand_id, "title": "Check draft", "text": "The Lumen Pods last 30 hours on one charge."}
    review = call(owner, "POST", "/api/reviews", 201, json=body, headers={"Idempotency-Key": key})
    replay = call(owner, "POST", "/api/reviews", 201, note="same key replays", json=body, headers={"Idempotency-Key": key})
    require(replay["id"] == review["id"], "idempotency key must replay the first review")
    require(replay.get("allowed_actions") == review.get("allowed_actions"), f"a replay must carry allowed_actions: {replay.get('allowed_actions')}")
    stub = str((review.get("engine") or {}).get("provider", "")).startswith("stub")
    for field in ("allowed_actions", "workflow_status", "risk_level", "routing_reason", "summary_counts", "approval_mode", "workspace", "author", "owner"):
        require(field in review, f"review is missing {field}")

    upload_review = call(
        owner,
        "POST",
        "/api/reviews/upload",
        201,
        data={"brand_id": brand_id, "title": "From a file"},
        files={"file": ("draft.txt", b"The Lumen Pods last 40 hours on one charge.", "text/plain")},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    require(upload_review["status"], "upload review")
    listed = call(owner, "GET", "/api/reviews", 200)
    require(any(r["id"] == review["id"] for r in listed), "the list includes the new review")
    require(not any(r["id"] == review["id"] for r in call(outsider, "GET", "/api/reviews", 200)), "another workspace's review must not be listed")
    call(owner, "GET", "/api/reviews/{review_id}", 200, path={"review_id": review["id"]})
    call(outsider, "GET", "/api/reviews/{review_id}", 404, note="other workspace", path={"review_id": review["id"]})
    call(None, "GET", "/api/reviews/{review_id}", 401, path={"review_id": review["id"]})
    call(owner, "POST", "/api/reviews/{review_id}/rerun", 201, path={"review_id": review["id"]}, headers={"Idempotency-Key": uuid.uuid4().hex})

    # --- Findings --------------------------------------------------------------------------
    current = call(owner, "GET", "/api/reviews/{review_id}", 200, path={"review_id": review["id"]})
    finding_id = current["findings"][0]["finding_id"]
    call(owner, "POST", "/api/findings/{finding_id}/dismiss", 201, path={"finding_id": finding_id}, json={"note": "Not relevant"})
    call(owner, "POST", "/api/findings/{finding_id}/dismiss", 409, note="already dismissed", path={"finding_id": finding_id}, json={})
    call(owner, "POST", "/api/findings/{finding_id}/restore", 201, path={"finding_id": finding_id}, json={})
    call(owner, "POST", "/api/findings/{finding_id}/comments", 201, path={"finding_id": finding_id}, json={"body": "A comment."})
    comments = call(owner, "GET", "/api/findings/{finding_id}/comments", 200, path={"finding_id": finding_id})
    require(len(comments) == 1, "the comment is listed")
    call(outsider, "GET", "/api/findings/{finding_id}/comments", 404, note="other workspace", path={"finding_id": finding_id})

    # --- Content, versions, locks ----------------------------------------------------------
    item_id = review["content_item_id"]
    version_id = review["content_version_id"]
    locks = call(owner, "PUT", "/api/content-versions/{content_version_id}/locks", 200, path={"content_version_id": version_id}, json={"locked_phrases": ["Lumen Pods"]})
    require(locks["locked_phrases"] == ["Lumen Pods"], "lock saved")
    call(owner, "GET", "/api/content-versions/{content_version_id}/locks", 200, path={"content_version_id": version_id})
    call(outsider, "GET", "/api/content-versions/{content_version_id}/locks", 404, note="other workspace", path={"content_version_id": version_id})
    call(owner, "GET", "/api/content/{content_item_id}/history", 200, path={"content_item_id": item_id})
    audit = call(owner, "GET", "/api/content/{content_item_id}/audit", 200, path={"content_item_id": item_id}, params={"limit": 5})
    require(audit["items"], "the draft has history")
    call(owner, "GET", "/api/content/{content_item_id}/audit", 422, note="bad cursor", path={"content_item_id": item_id}, params={"cursor": "!!bad!!"})
    call(outsider, "GET", "/api/content/{content_item_id}/audit", 404, note="other workspace", path={"content_item_id": item_id})
    newer = call(owner, "POST", "/api/content/{content_item_id}/versions", 201, path={"content_item_id": item_id}, json={"text": "The Lumen Pods last 24 hours on one charge."})
    require(newer["version_number"] == 2, "second version")
    call(owner, "POST", "/api/content-versions/{content_version_id}/approve", 409, note="stale version", path={"content_version_id": version_id})

    # --- Analytics and evaluations ---------------------------------------------------------
    call(owner, "GET", "/api/analytics/brand-risk", 200, params={"brand_id": brand_id})
    call(outsider, "GET", "/api/analytics/brand-risk", 404, note="other workspace", params={"brand_id": brand_id})
    call(owner, "GET", "/api/evaluations/latest", {200, 404})
    if stub:
        call(owner, "POST", "/api/evaluations", 409, note="no AI provider")
    else:
        called.add(("POST", "/api/evaluations"))
        print("skip  POST /api/evaluations: this server has an AI provider, and a run would spend its quota")

    # --- A team, and the whole workflow ----------------------------------------------------
    call(owner, "GET", "/api/workspace/members", 200)
    call(None, "GET", "/api/workspace/members", 401)
    call(owner, "GET", "/api/workspace/invitations", 200)
    writer, writer_home = join(owner, "writer", "writer")
    reviewer, _ = join(owner, "reviewer", "reviewer")
    approver, _ = join(owner, "approver", "approver")
    call(writer, "GET", "/api/workspace/invitations", 403, note="not an owner")
    call(writer, "POST", "/api/workspace/invitations", 403, note="not an owner", json={"email": "x@example.com", "role": "writer"})
    call(writer, "GET", "/api/workspace/audit", 403, note="not an owner")
    audit = call(owner, "GET", "/api/workspace/audit", 200)
    require(any(e["action"] == "invite_accepted" for e in audit["items"]), "the workspace log has the accepted invitation")

    me = call(writer, "GET", "/api/auth/me", 200)
    require(me.get("memberships_count") == 2, f"a teammate belongs to 2 workspaces: {me.get('memberships_count')}")
    require(me.get("workspace", {}).get("member_count") == 4, f"team of 4: {me.get('workspace')}")

    spaces = call(writer, "GET", "/api/workspaces", 200)
    require(len(spaces) == 2, "a teammate belongs to two workspaces")
    own = next(s for s in spaces if not s["is_current"])
    switched = call(writer, "POST", "/api/auth/switch-workspace", 200, json={"workspace_id": own["workspace"]["id"]})
    require(switched["organisation"]["id"] == own["workspace"]["id"], "switched workspace")
    call(writer, "POST", "/api/auth/switch-workspace", 404, note="not a member", json={"workspace_id": outsider["organisation"]["id"]})

    draft = new_review(writer, brand_id, "Team draft")
    require("approve" not in draft["allowed_actions"], "an author can't approve while someone else can")
    require(draft["approval_mode"] == "team", f"approval_mode: {draft['approval_mode']}")
    team_item, team_version = draft["content_item_id"], draft["content_version_id"]
    call(writer, "POST", "/api/content-versions/{content_version_id}/approve", 403, note="writer", path={"content_version_id": team_version})
    moved = call(writer, "POST", "/api/content/{content_item_id}/submit", 200, path={"content_item_id": team_item}, json={"content_version_id": team_version})
    require(moved["workflow_status"] in {"in_review", "submitted"}, f"submit: {moved['workflow_status']}")
    call(writer, "POST", "/api/content/{content_item_id}/assign", 403, note="writer", path={"content_item_id": team_item}, json={"reviewer_user_id": reviewer["user"]["id"]})
    moved = call(owner, "POST", "/api/content/{content_item_id}/assign", 200, path={"content_item_id": team_item}, json={"reviewer_user_id": reviewer["user"]["id"]})
    require(moved["assigned_reviewer"]["id"] == reviewer["user"]["id"], "assigned")
    call(writer, "POST", "/api/content/{content_item_id}/mark-reviewed", 403, note="author", path={"content_item_id": team_item}, json={"content_version_id": team_version})
    moved = call(reviewer, "POST", "/api/content/{content_item_id}/mark-reviewed", 200, path={"content_item_id": team_item}, json={"content_version_id": team_version, "note": "Checked."})
    require(moved["workflow_status"] == "reviewed", f"mark reviewed: {moved['workflow_status']}")
    call(reviewer, "POST", "/api/content-versions/{content_version_id}/approve", 403, note="reviewer", path={"content_version_id": team_version})
    call(approver, "POST", "/api/content-versions/{content_version_id}/approve", 201, path={"content_version_id": team_version})
    call(approver, "POST", "/api/content-versions/{content_version_id}/publish", 200, path={"content_version_id": team_version})
    final = call(owner, "GET", "/api/reviews/{review_id}", 200, path={"review_id": draft["id"]})
    require(final["workflow_status"] == "published", f"published: {final['workflow_status']}")

    sent_back = new_review(writer, brand_id, "Sent back")
    call(writer, "POST", "/api/content/{content_item_id}/submit", 200, path={"content_item_id": sent_back["content_item_id"]}, json={"content_version_id": sent_back["content_version_id"]})
    call(reviewer, "POST", "/api/content-versions/{content_version_id}/request-changes", 201, path={"content_version_id": sent_back["content_version_id"]}, json={"decision": "changes_requested", "note": "Fix it."})
    call(writer, "POST", "/api/content-versions/{content_version_id}/request-changes", 403, note="writer", path={"content_version_id": sent_back["content_version_id"]}, json={"decision": "rejected"})

    # --- Members and invitations -----------------------------------------------------------
    pending = call(owner, "POST", "/api/workspace/invitations", 201, json={"email": "check-pending@example.com", "role": "writer"})
    call(owner, "POST", "/api/workspace/invitations", 409, note="already pending", json={"email": "check-pending@example.com", "role": "writer"})
    call(owner, "POST", "/api/workspace/invitations/{invitation_id}/revoke", 200, path={"invitation_id": pending["invitation"]["id"]})
    call(owner, "POST", "/api/invitations/accept", {403, 409}, note="revoked", json={"token": pending["token"]})
    call(owner, "POST", "/api/workspace/invitations", 422, note="not a role", json={"email": "check-role@example.com", "role": "emperor"})

    call(writer, "PATCH", "/api/workspace/members/{user_id}", 403, note="not an owner", path={"user_id": reviewer["user"]["id"]}, json={"role": "owner"})
    call(owner, "PATCH", "/api/workspace/members/{user_id}", 403, note="own role", path={"user_id": owner["user"]["id"]}, json={"role": "writer"})
    call(owner, "PATCH", "/api/workspace/members/{user_id}", 200, path={"user_id": reviewer["user"]["id"]}, json={"role": "approver"})
    gone = call(owner, "DELETE", "/api/workspace/members/{user_id}", 409, note="last owner", path={"user_id": owner["user"]["id"]})
    require(code(gone) == "LAST_OWNER_REQUIRED", f"last owner code: {gone}")
    call(owner, "DELETE", "/api/workspace/members/{user_id}", 200, path={"user_id": writer["user"]["id"]})
    call(writer, "GET", "/api/workspace/members", 401, note="removed")
    require(writer_home["access_token"], "their own workspace session still exists")
    call(writer_home, "GET", "/api/workspace/members", 200, note="own workspace still works")

    # --- Did this cover everything the server publishes? ---------------------------------------
    missed = sorted(routes - called)
    for method, path in missed:
        failures.append(f"not checked: {method} {path}")
    unknown = sorted(c for c in called if c not in routes)
    for method, path in unknown:
        failures.append(f"checked a route the server doesn't publish: {method} {path}")

    print(f"\n{len(routes) - len(missed)} of {len(routes)} routes called, {passed} checks passed, {len(failures)} problems.")
    for failure in failures:
        print(f"  {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    # Guard against pointing this somewhere real.
    if not re.match(r"https?://(localhost|127\.0\.0\.1)", BASE_URL):
        sys.exit("This creates accounts. It only runs against localhost.")
    sys.exit(main())
