"""Frontend requests (2026-10-24).

1. POST /api/evaluations 429s say when to retry: a Retry-After header, copied into the body as
   error.retry_after (seconds) - the remaining part of the 10-minute window, or the running
   evaluation's time limit when one is already in progress;
   -> test_interval_429_says_how_long_to_wait
   -> test_already_running_429_says_how_long_to_wait
2. GET /api/content/{id}/history lists, per version, what the user did to that version's findings
   (dismissed / restored / commented), oldest first - never the comment text.
   -> test_history_lists_finding_events_per_version
"""

from __future__ import annotations

from conftest import requires_db
from inkloom_api.config import get_settings


def _scripted_eval(monkeypatch) -> None:
    from inkloom_api.engine.providers.fallback import FallbackProvider
    from inkloom_api.engine.scripted_provider import scripted_provider
    from inkloom_api.routers import evaluations

    monkeypatch.setattr(
        evaluations,
        "build_provider",
        lambda confidential=False, on_attempt=None: FallbackProvider(
            [("scripted", lambda: scripted_provider([]))], on_attempt=on_attempt
        ),
    )


@requires_db
def test_interval_429_says_how_long_to_wait(client, monkeypatch, account_factory) -> None:
    _scripted_eval(monkeypatch)
    owner = account_factory("owner", with_source=False)
    assert client.post("/api/evaluations", headers=owner.headers).status_code == 201

    again = client.post("/api/evaluations", headers=owner.headers)
    assert again.status_code == 429
    wait = int(again.headers["Retry-After"])
    interval = get_settings().eval_min_interval_seconds
    assert interval - 120 <= wait <= interval  # the rest of the window, not a fixed guess
    error = again.json()["error"]
    assert error["code"] == "RATE_LIMITED" and error["retry_after"] == wait


@requires_db
def test_already_running_429_says_how_long_to_wait(client, monkeypatch, account_factory) -> None:
    import uuid

    from inkloom_api.routers import evaluations

    _scripted_eval(monkeypatch)
    owner = account_factory("owner", with_source=False)
    monkeypatch.setattr(evaluations, "_in_flight", {uuid.UUID(owner.user_id)})
    response = client.post("/api/evaluations", headers=owner.headers)
    assert response.status_code == 429
    assert (
        response.json()["error"]["message"] == "an evaluation is already running for this account"
    )
    assert (
        int(response.headers["Retry-After"])
        == response.json()["error"]["retry_after"]
        == int(get_settings().eval_deadline_seconds)
    )


@requires_db
def test_history_lists_finding_events_per_version(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner")
    v1 = owner.submit()
    finding_id = v1["findings"][0]["finding_id"]
    secret = "zebra-comment-text-never-in-history"
    assert (
        client.post(
            f"/api/findings/{finding_id}/dismiss",
            json={"note": "fine for the US ad"},
            headers=owner.headers,
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/findings/{finding_id}/comments", json={"body": secret}, headers=owner.headers
        ).status_code
        == 201
    )
    assert (
        client.post(f"/api/findings/{finding_id}/restore", headers=owner.headers).status_code == 201
    )
    client.post(
        f"/api/content/{v1['content_item_id']}/versions",
        json={"text": "Lumen Pods offer 12 hours."},
        headers=owner.headers,
    )

    response = client.get(f"/api/content/{v1['content_item_id']}/history", headers=owner.headers)
    assert response.status_code == 200
    assert secret not in response.text
    first, second = response.json()["versions"]
    events = first["finding_events"]
    assert [(e["event_type"], e["finding_id"], e["actor_user_id"]) for e in events] == [
        ("finding.dismissed", finding_id, owner.user_id),
        ("finding.commented", finding_id, owner.user_id),
        ("finding.restored", finding_id, owner.user_id),
    ]
    assert [e["note"] for e in events] == ["fine for the US ad", None, None]
    assert set(events[0]) == {"event_type", "finding_id", "actor_user_id", "created_at", "note"}
    assert second["finding_events"] == []  # v2's own findings were not touched
