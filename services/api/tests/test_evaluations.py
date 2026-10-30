"""Trust Scorecard: GET /api/evaluations/latest and POST /api/evaluations (step 7).

Runs use the engine's real labelled dataset (services/verification/eval/dataset.jsonl; its size
and label split are read from the file, not hardcoded, so the dataset can grow; it grew from 55
to 80 claims in EVAL.md Phase 2) and the engine's real verifier, behind the offline scripted
provider - so the numbers below are exactly derivable from the labels.

1. latest before any run -> 404 NOT_FOUND (never 200 with missing numbers);
   -> test_latest_is_404_before_any_run
2. no provider configured -> 409, nothing stored, not counted against the rate limit;
   -> test_no_provider_is_409_and_stores_nothing
3. a run returns the Evaluation shape (201), stores it, logs its provider calls; numbers follow
   the engine's definitions (an always-abstaining checker flags everything: catch 1.0, FP 1.0);
   -> test_run_returns_evaluation_shape_and_is_stored
4. the call budget bounds the run: the rest become ERROR, status partial, noted in limits_note;
   -> test_call_budget_bounds_the_run
5. a run dominated by provider failures is not stored (409), its calls are still logged, and it
   still counts against the rate limit;
   -> test_failure_dominated_run_is_discarded
6. once per 10 minutes per user -> 429; another account never sees this account's run;
7. every run says what it covers (verifier only), gives dev and held-out metrics with their own
   denominators, and whether a live model or the scripted provider answered; runs stored before
   those fields existed still render.
   -> test_rate_limited_and_account_scoped
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import inkloom_verify
import pytest

from conftest import requires_db
from inkloom_api.config import get_settings
from inkloom_api.evaluation_runner import provider_mode
from inkloom_api.models import EvaluationRun, ExternalCallLog

DATASET = Path(inkloom_verify.__file__).resolve().parents[2] / "eval" / "dataset.jsonl"
RECORDS = [
    json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()
]
LABELS = [r["expected_verdict"] for r in RECORDS]
N = len(LABELS)
N_SUPPORTED = LABELS.count("SUPPORTED")
N_FLAGGABLE = N - N_SUPPORTED  # CONTRADICTED + NOT_ENOUGH_EVIDENCE
EVALUATION_KEYS = {"catch_rate", "false_positive_rate", "per_check", "sample_size", "run_at"}


@pytest.fixture
def scripted_eval(monkeypatch):
    """Every evaluation call answered by the scripted provider with no rules:
    NOT_ENOUGH_EVIDENCE."""
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


def _runs(db_session, account) -> int:
    db_session.expire_all()
    return (
        db_session.query(EvaluationRun)
        .filter_by(organisation_id=uuid.UUID(account.organisation_id))
        .count()
    )


@requires_db
def test_latest_is_404_before_any_run(client, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    response = client.get("/api/evaluations/latest", headers=owner.headers)
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "no evaluation has been run yet",
        "request_id": response.json()["error"]["request_id"],
    }


@requires_db
def test_no_provider_is_409_and_stores_nothing(
    client, force_stub_mode, db_session, account_factory
) -> None:
    owner = account_factory("owner", with_source=False)
    for _ in range(2):  # the second attempt is 409 again, not 429: nothing was stored
        response = client.post("/api/evaluations", headers=owner.headers)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CONFLICT"
        assert "no AI provider is configured" in response.json()["error"]["message"]
    assert _runs(db_session, owner) == 0
    assert client.get("/api/evaluations/latest", headers=owner.headers).status_code == 404


@requires_db
def test_run_returns_evaluation_shape_and_is_stored(
    client, scripted_eval, db_session, account_factory
) -> None:
    owner = account_factory("owner", with_source=False)
    response = client.post("/api/evaluations", headers=owner.headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) >= EVALUATION_KEYS

    assert body["sample_size"] == N
    assert body["catch_rate"] == 1.0  # every CONTRADICTED / NOT_ENOUGH_EVIDENCE claim flagged
    assert body["false_positive_rate"] == 1.0  # ...and every SUPPORTED claim flagged too
    overall = body["per_check"][0]
    assert overall == {
        "check": "verification",
        "catch_rate": 1.0,
        "false_positive_rate": 1.0,
        "n": N,
        "catch_rate_ratio": overall["catch_rate_ratio"],
        "false_positive_rate_ratio": overall["false_positive_rate_ratio"],
    }
    assert overall["catch_rate_ratio"]["value"] == 1.0
    assert overall["catch_rate_ratio"]["denominator"] + overall["false_positive_rate_ratio"][
        "denominator"
    ] == N, "every claim is in exactly one denominator"
    assert {
        "check",
        "catch_rate",
        "false_positive_rate",
        "n",
        "catch_rate_ratio",
        "false_positive_rate_ratio",
    } == set(body["per_check"][1])
    assert all(entry["n"] > 0 for entry in body["per_check"])
    assert body["status"] == "completed"
    assert body["provider_failure_rate"] == 0.0
    assert body["dataset_version"].startswith("dataset.jsonl@")
    assert body["engine_prompt_version"] == "verify-claim-v1"
    assert (
        "small test set" in body["limits_note"]
        and "not a universal accuracy" in body["limits_note"]
    )
    assert body["run_at"]

    assert body["coverage"] == "verifier_only"
    assert body["provider_mode"] == "scripted"
    splits = {r["split"] for r in RECORDS}
    assert set(body["by_split"]) == splits == {"dev", "heldout"}
    for split, entry in body["by_split"].items():
        subset = [r["expected_verdict"] for r in RECORDS if r["split"] == split]
        supported = subset.count("SUPPORTED")
        assert entry == {
            "n": len(subset),
            "catch_rate": {
                "numerator": len(subset) - supported,
                "denominator": len(subset) - supported,
                "value": 1.0,
            },
            "false_positive_rate": {"numerator": supported, "denominator": supported, "value": 1.0},
        }

    assert client.get("/api/evaluations/latest", headers=owner.headers).json() == body
    db_session.expire_all()
    calls = db_session.query(ExternalCallLog).filter_by(request_id=f"eval-{body['id']}").all()
    run = db_session.get(EvaluationRun, uuid.UUID(body["id"]))
    # One call per claim that retrieval found passages for (the engine skips the model when there
    # are none); every one of them is logged.
    assert 0 < len(calls) == run.metrics["calls_used"] <= N
    assert {c.review_id for c in calls} == {None}
    assert run.metrics["catch_rate"] == {
        "numerator": N_FLAGGABLE,
        "denominator": N_FLAGGABLE,
        "value": 1.0,
    }
    assert run.metrics["false_positive_rate"] == {
        "numerator": N_SUPPORTED,
        "denominator": N_SUPPORTED,
        "value": 1.0,
    }
    assert {str(c.organisation_id) for c in calls} == {owner.organisation_id}


@requires_db
def test_call_budget_bounds_the_run(
    client, scripted_eval, monkeypatch, db_session, account_factory
) -> None:
    monkeypatch.setattr(get_settings(), "eval_max_calls", 10)
    monkeypatch.setattr(
        get_settings(), "eval_max_provider_failure_rate", 1.0
    )  # keep the partial run
    owner = account_factory("owner", with_source=False)
    body = client.post("/api/evaluations", headers=owner.headers).json()
    db_session.expire_all()
    run = db_session.get(EvaluationRun, uuid.UUID(body["id"]))

    assert run.metrics["calls_used"] == 10  # the budget held
    errors = round(body["provider_failure_rate"] * N)
    assert body["status"] == "partial"
    assert (
        0 < errors <= N - 10
    )  # claims after the budget ran out got no verdict (a few need no call)
    # ERROR is neither flagged nor cleared: same denominators, fewer flagged.
    assert (
        run.metrics["catch_rate"]["denominator"] == N_FLAGGABLE
        and run.metrics["false_positive_rate"]["denominator"] == N_SUPPORTED
    )
    flagged = (
        run.metrics["catch_rate"]["numerator"] + run.metrics["false_positive_rate"]["numerator"]
    )
    assert flagged == N - errors  # every answered claim was flagged (always-abstaining checker)
    assert (
        body["catch_rate"] == round(run.metrics["catch_rate"]["numerator"] / N_FLAGGABLE, 4) < 1.0
    )
    # The per-split numbers partition the pooled ones: nothing counted twice or dropped.
    for rate in ("catch_rate", "false_positive_rate"):
        for part in ("numerator", "denominator"):
            assert sum(s[rate][part] for s in body["by_split"].values()) == run.metrics[rate][part]
    assert "got no verdict" in body["limits_note"]


@requires_db
def test_failure_dominated_run_is_discarded(
    client, scripted_eval, monkeypatch, db_session, account_factory
) -> None:
    monkeypatch.setattr(get_settings(), "eval_max_calls", 10)  # ~80% of claims get no verdict
    owner = account_factory("owner", with_source=False)
    response = client.post("/api/evaluations", headers=owner.headers)
    assert response.status_code == 409
    assert "was not saved" in response.json()["error"]["message"]
    assert _runs(db_session, owner) == 0
    assert client.get("/api/evaluations/latest", headers=owner.headers).status_code == 404
    db_session.expire_all()
    assert (
        db_session.query(ExternalCallLog)
        .filter(
            ExternalCallLog.organisation_id == uuid.UUID(owner.organisation_id),
            ExternalCallLog.request_id.like("eval-%"),
        )
        .count()
        == 10
    )  # the real calls stay on record
    assert client.post("/api/evaluations", headers=owner.headers).status_code == 429


@requires_db
def test_rate_limited_and_account_scoped(client, scripted_eval, account_factory) -> None:
    owner, other = (
        account_factory("owner", with_source=False),
        account_factory("other", with_source=False),
    )
    assert client.post("/api/evaluations", headers=owner.headers).status_code == 201

    again = client.post("/api/evaluations", headers=owner.headers)
    assert again.status_code == 429
    assert again.json()["error"]["code"] == "RATE_LIMITED"

    # Another account: never sees owner's run, and has its own allowance.
    assert client.get("/api/evaluations/latest", headers=other.headers).status_code == 404
    assert client.post("/api/evaluations", headers=other.headers).status_code == 201
    assert client.post("/api/evaluations").status_code == 401


@requires_db
def test_run_stored_before_new_fields_still_renders(client, db_session, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    ratio = {"numerator": 1, "denominator": 1, "value": 1.0}
    db_session.add(
        EvaluationRun(
            organisation_id=uuid.UUID(owner.organisation_id),
            status="completed",
            ran_at=datetime.now(UTC),
            engine_prompt_version="verify-claim-v1",
            dataset_version="dataset.jsonl@000000000000",
            sample_size=55,
            metrics={
                "catch_rate": ratio,
                "false_positive_rate": ratio,
                "per_check": [],
                "model_ids": ["gemini-3.5-flash-lite"],
            },
            limits_note="older run",
        )
    )
    db_session.commit()
    body = client.get("/api/evaluations/latest", headers=owner.headers).json()
    assert body["coverage"] == "verifier_only"  # the only thing the runner has ever measured
    assert body["by_split"] is None  # not recomputed: per-claim predictions were never stored
    assert body["provider_mode"] == "live"
    # An older run has no held-out split or per-check counts: absent, never invented.
    assert body["headline"] is None
    assert body["catch_rate_ratio"] == ratio


@requires_db
def test_headline_is_the_stored_held_out_split_and_counts_are_served(
    client, db_session, account_factory
) -> None:
    owner = account_factory("owner", with_source=False)
    ratio = {"numerator": 3, "denominator": 4, "value": 0.75}
    heldout = {
        "n": 25,
        "catch_rate": {"numerator": 18, "denominator": 18, "value": 1.0},
        "false_positive_rate": {"numerator": 1, "denominator": 7, "value": 1 / 7},
    }
    db_session.add(
        EvaluationRun(
            organisation_id=uuid.UUID(owner.organisation_id),
            status="completed",
            ran_at=datetime.now(UTC),
            dataset_version="dataset.jsonl@000000000000",
            sample_size=80,
            metrics={
                "catch_rate": ratio,
                "false_positive_rate": ratio,
                "per_check": [
                    {
                        "check": "verification",
                        "catch_rate": 0.75,
                        "false_positive_rate": 0.75,
                        "n": 80,
                        "catch_rate_ratio": ratio,
                        "false_positive_rate_ratio": ratio,
                    },
                    {"check": "older", "catch_rate": 0.5, "false_positive_rate": None, "n": 2},
                ],
                "by_split": {
                    "dev": {"n": 55, "catch_rate": ratio, "false_positive_rate": ratio},
                    "heldout": heldout,
                },
                "model_ids": ["gemini-3.5-flash-lite"],
            },
            limits_note="a run",
        )
    )
    db_session.commit()
    body = client.get("/api/evaluations/latest", headers=owner.headers).json()
    assert body["headline"] == {"split": "heldout", **heldout}, "copied, not computed"
    assert body["catch_rate_ratio"] == ratio
    assert body["false_positive_rate_ratio"] == ratio
    assert body["per_check"][0]["catch_rate_ratio"] == ratio
    assert body["per_check"][1]["catch_rate_ratio"] is None


def test_provider_mode_from_answering_models() -> None:
    assert provider_mode(["gemini-3.5-flash-lite", "nvidia/nemotron-3.5-super-vl:free"]) == "live"
    assert provider_mode(["scripted/demo-v1"]) == "scripted"
    assert provider_mode(["scripted/demo-v1", "gemini-3.5-flash-lite"]) == "mixed"
    assert provider_mode([]) is None
