"""GET /api/reviews - the Review queue page (step 5). queue.ts calls
`request<ReviewOut[]>("/api/reviews?status=needs_human_review")`, so the response must be a plain
JSON array of full ReviewOut objects (findings included), newest first.

1. plain array of full ReviewOut objects, own account only, newest first;
   -> test_lists_own_reviews_as_plain_array_newest_first
2. status filter (single and repeated) and brand filter;
   -> test_status_filter_single_and_repeated
   -> test_brand_filter
3. empty account -> [], unknown filters -> [];
   -> test_empty_account_returns_empty_array
4. another account's brand_id (or a random one) -> the same 404, no leak;
   -> test_other_accounts_brand_id_is_404
5. pagination: limit/offset, default 50, max 100, bad values -> 422; bad status -> 422.
   -> test_pagination_and_validation
6. requires authentication.
   -> test_requires_auth
"""

from __future__ import annotations

import uuid

from conftest import requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule

RULES = [
    ScriptedRule(
        "24 hours", "CONTRADICTED", "up to 12 hours of playback per charge", "12 hours, not 24."
    ),
    ScriptedRule("12 hours", "SUPPORTED", "up to 12 hours of playback per charge", "Stated."),
]


def _list(client, account, query: str = ""):
    return client.get(f"/api/reviews{query}", headers=account.headers)


@requires_db
def test_lists_own_reviews_as_plain_array_newest_first(
    client, monkeypatch, account_factory
) -> None:
    use_scripted_provider(monkeypatch, RULES)
    owner, other = account_factory("owner"), account_factory("other")
    other.submit("Other account's draft: up to 24 hours.")
    first = owner.submit("Lumen Pods offer up to 12 hours of playback per charge.", title="First")
    second = owner.submit("Lumen Pods offer up to 24 hours of playback per charge.", title="Second")

    response = _list(client, owner)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)  # not wrapped in an object
    assert [r["id"] for r in body] == [
        second["id"],
        first["id"],
    ]  # newest first, other account absent
    newest = body[0]
    # Full ReviewOut, identical to GET /api/reviews/{id} - not a slim row.
    assert newest == client.get(f"/api/reviews/{second['id']}", headers=owner.headers).json()
    assert newest["findings"][0]["evidence"][0]["source_title"] == "Fact Sheet"
    assert newest["title"] == "Second" and newest["brand_name"]


@requires_db
def test_status_filter_single_and_repeated(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, RULES)
    owner = account_factory("owner")
    clean = owner.submit("Lumen Pods offer up to 12 hours of playback per charge.")  # completed
    flagged = owner.submit(
        "Lumen Pods offer up to 24 hours of playback per charge."
    )  # needs_human_review
    decided = owner.submit("Lumen Pods have 24 hours of playback.")
    client.post(
        f"/api/content-versions/{decided['content_version_id']}/request-changes",
        json={"decision": "changes_requested"},
        headers=owner.headers,
    )

    needs = _list(client, owner, "?status=needs_human_review").json()
    assert [r["id"] for r in needs] == [flagged["id"]]
    both = _list(client, owner, "?status=needs_human_review&status=completed").json()
    assert {r["id"] for r in both} == {flagged["id"], clean["id"]}
    changes = _list(client, owner, "?status=changes_requested").json()
    assert [r["id"] for r in changes] == [decided["id"]] and changes[0][
        "status"
    ] == "changes_requested"


@requires_db
def test_brand_filter(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner")
    second_brand = owner.create_brand("Second brand")
    owner.upload_source(brand_id=second_brand["id"])
    in_first = owner.submit("First brand draft.")
    in_second = owner.submit("Second brand draft.", brand_id=second_brand["id"])

    assert [r["id"] for r in _list(client, owner, f"?brand_id={owner.brand_id}").json()] == [
        in_first["id"]
    ]
    assert [r["id"] for r in _list(client, owner, f"?brand_id={second_brand['id']}").json()] == [
        in_second["id"]
    ]
    combined = _list(
        client, owner, f"?brand_id={second_brand['id']}&status=needs_human_review"
    ).json()
    assert [r["id"] for r in combined] == [in_second["id"]]


@requires_db
def test_empty_account_returns_empty_array(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner")
    assert _list(client, owner).json() == []
    assert _list(client, owner, "?status=needs_human_review").json() == []
    owner.submit()
    assert _list(client, owner, "?status=approved").json() == []
    assert _list(client, owner, "?offset=10").json() == []


@requires_db
def test_other_accounts_brand_id_is_404(client, force_stub_mode, account_factory) -> None:
    owner, other = account_factory("owner"), account_factory("other")
    other.submit()
    theirs = _list(client, owner, f"?brand_id={other.brand_id}")
    random_brand = _list(client, owner, f"?brand_id={uuid.uuid4()}")
    assert theirs.status_code == random_brand.status_code == 404
    assert theirs.json()["error"]["code"] == "NOT_FOUND"
    assert theirs.json()["error"]["message"] == random_brand.json()["error"]["message"]


@requires_db
def test_pagination_and_validation(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner")
    ids = [owner.submit(f"Draft number {i}.")["id"] for i in range(5)]
    newest_first = list(reversed(ids))

    assert [r["id"] for r in _list(client, owner, "?limit=2").json()] == newest_first[:2]
    assert [r["id"] for r in _list(client, owner, "?limit=2&offset=2").json()] == newest_first[2:4]
    assert [r["id"] for r in _list(client, owner, "?limit=2&offset=4").json()] == newest_first[4:]
    assert len(_list(client, owner).json()) == 5  # default limit 50 covers all
    assert _list(client, owner, "?limit=100").status_code == 200
    for bad in ("?limit=101", "?limit=0", "?offset=-1", "?status=bogus", "?brand_id=not-a-uuid"):
        response = _list(client, owner, bad)
        assert response.status_code == 422, bad
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@requires_db
def test_requires_auth(client) -> None:
    response = client.get("/api/reviews")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
