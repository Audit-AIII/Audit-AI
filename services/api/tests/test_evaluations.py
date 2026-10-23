"""`GET /api/evaluations/latest` (Trust Scorecard): auth, the three states, and that the backend
serves the engine's summary without computing or echoing anything itself.

Summaries here are written by the engine's own code (inkloom_verify.evaluation) from its
hand-built TEST FIXTURE (services/verification/eval/fixtures/required_metrics), never a real run."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

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
