<<<<<<< HEAD
"""Trust Scorecard: GET /api/evaluations/latest and POST /api/evaluations (step 7).

Runs use the engine's real labelled dataset (services/verification/eval/dataset.jsonl, 55 claims:
20 SUPPORTED, 17 CONTRADICTED, 18 NOT_ENOUGH_EVIDENCE) and the engine's real verifier, behind the
offline scripted provider - so the numbers below are exactly derivable from the labels.

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
6. once per 10 minutes per user -> 429; another account never sees this account's run.
   -> test_rate_limited_and_account_scoped
"""
=======
"""`GET /api/evaluations/latest` (Trust Scorecard): auth, the three states, and that the backend
serves the engine's summary without computing or echoing anything itself.

Summaries here are written by the engine's own code (inkloom_verify.evaluation) from its
hand-built TEST FIXTURE (services/verification/eval/fixtures/required_metrics), never a real run."""
>>>>>>> 6b23c112bb2360f3710bc25c6629254199b169ad

from __future__ import annotations

import json
import uuid
from pathlib import Path

<<<<<<< HEAD
import inkloom_verify
import pytest

from conftest import requires_db
from inkloom_api.config import get_settings
from inkloom_api.models import EvaluationRun, ExternalCallLog

DATASET = Path(inkloom_verify.__file__).resolve().parents[2] / "eval" / "dataset.jsonl"
LABELS = [json.loads(line)["expected_verdict"] for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
EVALUATION_KEYS = {"catch_rate", "false_positive_rate", "per_check", "sample_size", "run_at"}


@pytest.fixture
def scripted_eval(monkeypatch):
    """Every evaluation call answered by the scripted provider with no rules: NOT_ENOUGH_EVIDENCE."""
    from inkloom_api.engine.providers.fallback import FallbackProvider
    from inkloom_api.engine.scripted_provider import scripted_provider
    from inkloom_api.routers import evaluations

    monkeypatch.setattr(
        evaluations, "build_provider",
        lambda confidential=False, on_attempt=None: FallbackProvider([("scripted", lambda: scripted_provider([]))], on_attempt=on_attempt),
    )


def _runs(db_session, account) -> int:
    db_session.expire_all()
    return db_session.query(EvaluationRun).filter_by(organisation_id=uuid.UUID(account.organisation_id)).count()


@requires_db
def test_latest_is_404_before_any_run(client, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    response = client.get("/api/evaluations/latest", headers=owner.headers)
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND", "message": "no evaluation has been run yet", "request_id": response.json()["error"]["request_id"]
    }


@requires_db
def test_no_provider_is_409_and_stores_nothing(client, force_stub_mode, db_session, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    for _ in range(2):  # the second attempt is 409 again, not 429: nothing was stored
        response = client.post("/api/evaluations", headers=owner.headers)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CONFLICT"
        assert "no AI provider is configured" in response.json()["error"]["message"]
    assert _runs(db_session, owner) == 0
    assert client.get("/api/evaluations/latest", headers=owner.headers).status_code == 404


@requires_db
def test_run_returns_evaluation_shape_and_is_stored(client, scripted_eval, db_session, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    response = client.post("/api/evaluations", headers=owner.headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert EVALUATION_KEYS <= set(body)

    assert body["sample_size"] == len(LABELS) == 55
    assert body["catch_rate"] == 1.0  # every CONTRADICTED / NOT_ENOUGH_EVIDENCE claim flagged
    assert body["false_positive_rate"] == 1.0  # ...and every SUPPORTED claim flagged too
    overall = body["per_check"][0]
    assert overall == {"check": "verification", "catch_rate": 1.0, "false_positive_rate": 1.0, "n": 55}
    assert {"check", "catch_rate", "false_positive_rate", "n"} == set(body["per_check"][1])
    assert all(entry["n"] > 0 for entry in body["per_check"])
    assert body["status"] == "completed"
    assert body["provider_failure_rate"] == 0.0
    assert body["dataset_version"].startswith("dataset.jsonl@")
    assert body["engine_prompt_version"] == "verify-claim-v1"
    assert "small test set" in body["limits_note"] and "not a universal accuracy" in body["limits_note"]
    assert body["run_at"]

    assert client.get("/api/evaluations/latest", headers=owner.headers).json() == body
    db_session.expire_all()
    calls = db_session.query(ExternalCallLog).filter_by(request_id=f"eval-{body['id']}").all()
    run = db_session.get(EvaluationRun, uuid.UUID(body["id"]))
    # One call per claim that retrieval found passages for (the engine skips the model when there
    # are none); every one of them is logged.
    assert 0 < len(calls) == run.metrics["calls_used"] <= 55
    assert {c.review_id for c in calls} == {None}
    assert run.metrics["catch_rate"] == {"numerator": 35, "denominator": 35, "value": 1.0}
    assert run.metrics["false_positive_rate"] == {"numerator": 20, "denominator": 20, "value": 1.0}
    assert {str(c.organisation_id) for c in calls} == {owner.organisation_id}


@requires_db
def test_call_budget_bounds_the_run(client, scripted_eval, monkeypatch, db_session, account_factory) -> None:
    monkeypatch.setattr(get_settings(), "eval_max_calls", 10)
    monkeypatch.setattr(get_settings(), "eval_max_provider_failure_rate", 1.0)  # keep the partial run
    owner = account_factory("owner", with_source=False)
    body = client.post("/api/evaluations", headers=owner.headers).json()
    db_session.expire_all()
    run = db_session.get(EvaluationRun, uuid.UUID(body["id"]))

    assert run.metrics["calls_used"] == 10  # the budget held
    errors = round(body["provider_failure_rate"] * 55)
    assert body["status"] == "partial"
    assert 0 < errors <= 45  # claims after the budget ran out got no verdict (a few need no call)
    # ERROR is neither flagged nor cleared: same denominators, fewer flagged.
    assert run.metrics["catch_rate"]["denominator"] == 35 and run.metrics["false_positive_rate"]["denominator"] == 20
    flagged = run.metrics["catch_rate"]["numerator"] + run.metrics["false_positive_rate"]["numerator"]
    assert flagged == 55 - errors  # every answered claim was flagged (always-abstaining checker)
    assert body["catch_rate"] == round(run.metrics["catch_rate"]["numerator"] / 35, 4) < 1.0
    assert "got no verdict" in body["limits_note"]


@requires_db
def test_failure_dominated_run_is_discarded(client, scripted_eval, monkeypatch, db_session, account_factory) -> None:
    monkeypatch.setattr(get_settings(), "eval_max_calls", 10)  # ~80% of claims get no verdict
    owner = account_factory("owner", with_source=False)
    response = client.post("/api/evaluations", headers=owner.headers)
    assert response.status_code == 409
    assert "was not saved" in response.json()["error"]["message"]
    assert _runs(db_session, owner) == 0
    assert client.get("/api/evaluations/latest", headers=owner.headers).status_code == 404
    db_session.expire_all()
    assert db_session.query(ExternalCallLog).filter(
        ExternalCallLog.organisation_id == uuid.UUID(owner.organisation_id),
        ExternalCallLog.request_id.like("eval-%"),
    ).count() == 10  # the real calls stay on record
    assert client.post("/api/evaluations", headers=owner.headers).status_code == 429


@requires_db
def test_rate_limited_and_account_scoped(client, scripted_eval, account_factory) -> None:
    owner, other = account_factory("owner", with_source=False), account_factory("other", with_source=False)
    assert client.post("/api/evaluations", headers=owner.headers).status_code == 201

    again = client.post("/api/evaluations", headers=owner.headers)
    assert again.status_code == 429
    assert again.json()["error"]["code"] == "RATE_LIMITED"

    # Another account: never sees owner's run, and has its own allowance.
    assert client.get("/api/evaluations/latest", headers=other.headers).status_code == 404
    assert client.post("/api/evaluations", headers=other.headers).status_code == 201
    assert client.post("/api/evaluations").status_code == 401
=======
import pytest

from conftest import requires_db

VERIFICATION = Path(__file__).resolve().parents[2] / "verification"
PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def cleanup(db_session):
    from inkloom_api.models import Organisation, User

    created: list[tuple[uuid.UUID, uuid.UUID]] = []
    yield created
    for org_id, user_id in created:
        if (org := db_session.get(Organisation, org_id)) is not None:
            db_session.delete(org)
        if (user := db_session.get(User, user_id)) is not None:
            db_session.delete(user)
    db_session.commit()


@pytest.fixture
def token(client, cleanup) -> str:
    response = client.post("/api/auth/register", json={"email": f"eval-{uuid.uuid4().hex[:10]}@example.com", "password": PASSWORD})
    assert response.status_code == 201, response.text
    body = response.json()
    cleanup.append((uuid.UUID(body["organisation"]["id"]), uuid.UUID(body["user"]["id"])))
    return body["access_token"]


@pytest.fixture
def reports_dir(tmp_path, monkeypatch):
    from inkloom_api.config import get_settings

    directory = tmp_path / "eval" / "reports"
    monkeypatch.setenv("EVALUATION_REPORTS_DIR", str(directory))
    get_settings.cache_clear()
    yield directory
    get_settings.cache_clear()


def fixture_summary(directory: Path, created_at: str = "2026-10-24T10:20:30+00:00", incomplete: bool = False) -> None:
    """Writes a summary with the engine's own writer, from its hand-built test fixture."""
    from inkloom_verify.evaluation import report as rep
    from inkloom_verify.evaluation.summary import build_summary, incomplete_summary
    from inkloom_verify.evaluation.pipeline_predictor import CaseOutcome
    from inkloom_verify.evaluation import required_metrics as rm
    from inkloom_verify.evaluation.runner import load_predictions, load_records

    if incomplete:
        report = {"run": {"created_at": created_at, "incomplete": True, "error": "ProviderNotConfiguredError: not configured",
                          "verdict_source": "openrouter"}}
        rep.write_report(report, directory, None, incomplete_summary(report).model_dump(mode="json"))
        return
    fixture = VERIFICATION / "eval" / "fixtures" / "required_metrics"
    records = {r.record_id: r for r in load_records(fixture / "dataset.jsonl")}
    cases = {c.record_id: c for c in (CaseOutcome.model_validate_json(l)
                                      for l in (fixture / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}
    metrics = rm.compute(list(records.values()), load_predictions(fixture / "predictions.jsonl"), cases).model_dump(mode="json")
    report = {
        "run": {"created_at": created_at, "verdict_source": "oracle", "pipeline": "full", "engine_version": "0.1.0",
                "dataset": {"path": "eval/fixtures/required_metrics/dataset.jsonl", "sha256": "f" * 64, "records": 8, "locked": False,
                            "labels": {}, "groups": None},
                "model_configuration": {"provider": "oracle"}, "prompt_versions": {"verify_claim": "verify-claim-v1"},
                "retrieval_parameters": {}, "decision_policy": {}},
        "datasets": {"human_reviewed": 0},
        "verdicts": {"is_model_quality": False, "examples": 8, "model_ids": [], "prompt_versions_sent": [], "failure_counts": {},
                     "confusion": {"SUPPORTED": {"SUPPORTED": 1}, "CONTRADICTED": {"SUPPORTED": 0},
                                   "NOT_ENOUGH_EVIDENCE": {"SUPPORTED": 1}}},
        "required_metrics": metrics, "gates": [],
    }
    rep.write_report(report, directory, None, build_summary(report, cases, records).model_dump(mode="json"))


def test_an_unauthenticated_request_is_refused(client) -> None:
    response = client.get("/api/evaluations/latest")
    assert response.status_code == 401 and response.json()["error"]["code"] == "UNAUTHENTICATED"


@requires_db
def test_no_report_yet_is_a_clear_empty_state(client, token, reports_dir) -> None:
    response = client.get("/api/evaluations/latest", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "none" and body["contract"] == "evaluation-summary-v1" and "run_eval.py" in body["how_to_run"]


@requires_db
def test_the_latest_summary_is_served_as_the_engine_wrote_it(client, token, reports_dir) -> None:
    fixture_summary(reports_dir, "2026-10-23T09:00:00+00:00")
    fixture_summary(reports_dir, "2026-10-24T10:20:30+00:00")
    body = client.get("/api/evaluations/latest", headers={"Authorization": f"Bearer {token}"}).json()
    written = json.loads((reports_dir / "20261024T102030Z.summary.json").read_text(encoding="utf-8"))
    assert body == written  # nothing recomputed, nothing added
    assert body["state"] == "available" and body["report_id"] == "20261024T102030Z"
    assert len(body["metrics"]) == 8 and body["source"]["is_model_quality"] is False


@requires_db
def test_an_incomplete_newest_run_is_shown_as_incomplete(client, token, reports_dir) -> None:
    fixture_summary(reports_dir, "2026-10-23T09:00:00+00:00")
    fixture_summary(reports_dir, "2026-10-24T10:20:30+00:00", incomplete=True)
    body = client.get("/api/evaluations/latest", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["state"] == "incomplete" and "not configured" in body["error"]


@requires_db
def test_a_broken_report_is_a_generic_500_that_never_echoes_its_contents(client, token, reports_dir) -> None:
    reports_dir.mkdir(parents=True)
    (reports_dir / "20261024T102030Z.summary.json").write_text('{"state": "available", "secret": "sk-or-v1-NOT-REAL"}', encoding="utf-8")
    response = client.get("/api/evaluations/latest", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 500
    assert "sk-or" not in response.text and response.json()["error"]["message"] == "the latest evaluation report could not be read"
>>>>>>> 6b23c112bb2360f3710bc25c6629254199b169ad
