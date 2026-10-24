"""scripts/seed.py (step 8): two individual demo accounts that exercise every page of the UI.

Runs the real seed functions with unique emails (so a developer's own demo accounts are never
touched), then checks through the HTTP API, logged in as each demo user:

* their own account only, two brands, approved sources, all labelled [SEEDED];
* reviews in completed / needs_human_review / approved / changes_requested;
* one content item with 2+ versions; one withdrawn source with an approved item now source_changed;
* an "India's number one ..." claim flagged unverified; a contradicted claim with a suggestion;
* every seeded review came from the scripted provider, never a real model;
* idempotent (a second run skips both users) and --reset reseeds from scratch.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

from conftest import requires_db

SEED_PATH = Path(__file__).resolve().parent.parent / "scripts" / "seed.py"


@pytest.fixture
def seed_module(db_session):
    spec = importlib.util.spec_from_file_location("seed_under_test", SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_under_test"] = module
    spec.loader.exec_module(module)
    unique = uuid.uuid4().hex[:8]
    module.DEMO_USERS = [
        dataclasses.replace(user, email=f"{user.email.split('@')[0]}-{unique}@seed.example.com")
        for user in module.DEMO_USERS
    ]
    yield module
    for user in module.DEMO_USERS:
        module.reset_user(db_session, user.email)
    sys.modules.pop("seed_under_test", None)


def _login(client, module, email: str) -> dict:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": module.DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@requires_db
def test_seed_creates_two_demo_accounts_covering_every_state(
    client, seed_module, db_session
) -> None:
    seed_module.seed()
    [asha, ben] = seed_module.DEMO_USERS
    accounts = {}
    for demo in (asha, ben):
        headers = _login(client, seed_module, demo.email)
        me = client.get("/api/auth/me", headers=headers).json()
        assert me["role"] == "admin"  # account owner
        brands = client.get("/api/brands", headers=headers).json()
        assert len(brands) == 2 and all(
            "[SEEDED]" in b["name"] and b["approved_source_count"] >= 1 for b in brands
        )
        reviews = client.get("/api/reviews?limit=100", headers=headers).json()
        accounts[demo.email] = (headers, brands, reviews)

        statuses = {r["status"] for r in reviews}
        assert {
            "completed",
            "needs_human_review",
            "approved",
            "changes_requested",
            "source_changed",
        } <= statuses
        assert all(r["title"].startswith("[SEEDED]") for r in reviews)
        assert {r["engine"]["model_id"] for r in reviews} == {
            "scripted/demo-v1"
        }  # never a real model

        findings = [f for r in reviews for f in r["findings"]]
        number_one = [f for f in findings if "number one" in f["original_text"]]
        assert number_one and all(
            f["verification_status"] == "unverified" and not f["evidence"] for f in number_one
        )
        assert any(
            f["verification_status"] == "contradicted" and f["suggested_correction"]
            for f in findings
        )

        item_ids = [r["content_item_id"] for r in reviews]
        multi = [i for i in set(item_ids) if item_ids.count(i) >= 2]
        assert multi, "expected one content item with 2+ versions"
        history = client.get(f"/api/content/{multi[0]}/history", headers=headers).json()
        assert len(history["versions"]) >= 2
        assert history["versions"][0]["decisions"][0]["action"] == "changes_requested"

        withdrawn = [
            s
            for b in brands
            for s in client.get(f"/api/brands/{b['id']}/sources", headers=headers).json()
            if s["status"] in ("superseded", "archived")
        ]
        assert len(withdrawn) == 1

        risk = client.get(
            f"/api/analytics/brand-risk?brand_id={brands[0]['id']}", headers=headers
        ).json()
        assert risk["sample_size"] > 0 and risk["top_categories"]
        assert (
            risk["median_turnaround_minutes"] is not None
        )  # seeded decisions have real timestamps

    # Each demo user sees only their own data.
    asha_headers, asha_brands, asha_reviews = accounts[asha.email]
    ben_headers, ben_brands, _ = accounts[ben.email]
    assert (
        client.get(f"/api/reviews/{asha_reviews[0]['id']}", headers=ben_headers).status_code == 404
    )
    assert (
        client.get(f"/api/reviews?brand_id={ben_brands[0]['id']}", headers=asha_headers).status_code
        == 404
    )


@requires_db
def test_seed_is_idempotent_and_reset_reseeds(client, seed_module, db_session, capsys) -> None:
    seed_module.seed()
    [asha, _] = seed_module.DEMO_USERS
    first_brand_ids = {
        b["id"]
        for b in client.get("/api/brands", headers=_login(client, seed_module, asha.email)).json()
    }

    seed_module.seed()
    assert capsys.readouterr().out.count("already seeded - skipped") == 2
    same = {
        b["id"]
        for b in client.get("/api/brands", headers=_login(client, seed_module, asha.email)).json()
    }
    assert same == first_brand_ids

    seed_module.seed(reset=True)
    fresh = {
        b["id"]
        for b in client.get("/api/brands", headers=_login(client, seed_module, asha.email)).json()
    }
    assert len(fresh) == 2 and fresh.isdisjoint(first_brand_ids)
