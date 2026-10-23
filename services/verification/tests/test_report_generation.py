"""EVAL.md Phase 7/8: the report generator (evaluation/report.py) and the Trust Scorecard summary
contract (evaluation/summary.py).

The inputs are deterministic TEST FIXTURES: the hand-built required-metrics fixture
(eval/fixtures/required_metrics/) plus hand-written run metadata. They test formatting and error
handling only; nothing here is a model-evaluation result."""

import copy
import json
from pathlib import Path

import pytest

from inkloom_verify.evaluation import report as rep
from inkloom_verify.evaluation import required_metrics as rm
from inkloom_verify.evaluation.pipeline_predictor import CaseOutcome
from inkloom_verify.evaluation.runner import load_predictions, load_records
from inkloom_verify.evaluation.summary import (
    EvaluationSummary,
    IncompleteEvaluation,
    NoEvaluation,
    SummaryInvalid,
    build_summary,
    incomplete_summary,
    latest_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "eval" / "fixtures" / "required_metrics"
RECORDS = {r.record_id: r for r in load_records(FIXTURE / "dataset.jsonl")}
CASES = {c.record_id: c for c in (CaseOutcome.model_validate_json(l) for l in (FIXTURE / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}
METRICS = rm.compute(list(RECORDS.values()), load_predictions(FIXTURE / "predictions.jsonl"), CASES).model_dump(mode="json")
LABELS = ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE", "ERROR")


def fixture_report(**changes) -> dict:
    """A complete runner result, built from the fixture: TP 2, FP 1, FN 2, TN 3 (see test_required_metrics)."""
    report = {
        "run": {"created_at": "2026-10-24T10:20:30+00:00", "engine_version": "0.1.0", "python": "3.12.0", "git_commit": "abc123",
                "git_dirty": False, "verdict_source": "oracle", "pipeline": "full",
                "dataset": {"path": "eval/fixtures/required_metrics/dataset.jsonl", "sha256": "f" * 64, "records": 8, "locked": True,
                            "labels": {"SUPPORTED": 2, "CONTRADICTED": 4, "NOT_ENOUGH_EVIDENCE": 2}, "groups": None},
                "model_configuration": {"provider": "oracle"}, "prompt_versions": {"verify_claim": "verify-claim-v1"},
                "retrieval_parameters": {"retrieval": {"top_k": 5}},
                "decision_policy": {"policy": {"version": "decision-policy-v1", "thresholds": {"auto_clear_min_strength": "strong"},
                                               "uses_model_confidence": False},
                                    "calibration": {"status": "not calibrated", "split": "dev"}},
                "evaluation_failed": False},
        "datasets": {"human_reviewed": 0},
        "verdicts": {"source": "oracle", "is_model_quality": False, "model_ids": ["oracle/gold-labels"],
                     "prompt_versions_sent": ["verify-claim-v1"], "examples": 8, "failure_counts": {},
                     "confusion": {"SUPPORTED": {"SUPPORTED": 1, "CONTRADICTED": 1, "NOT_ENOUGH_EVIDENCE": 0, "ERROR": 0},
                                   "CONTRADICTED": {"SUPPORTED": 0, "CONTRADICTED": 2, "NOT_ENOUGH_EVIDENCE": 1, "ERROR": 1},
                                   "NOT_ENOUGH_EVIDENCE": {"SUPPORTED": 1, "CONTRADICTED": 0, "NOT_ENOUGH_EVIDENCE": 0, "ERROR": 1}}},
        "required_metrics": copy.deepcopy(METRICS),
        "gates": [
            {"name": "oracle: CONTRADICTED recall (engine ceiling)", "metric": "required_metrics/contradicted_recall", "op": ">=",
             "value": 1.0, "applies_to": "oracle", "status": "FAIL", "measured": 0.5, "note": "measured 32/32"},
            {"name": "pipeline safety: auto-cleared", "metric": "x", "op": "<=", "value": 0, "applies_to": "always",
             "status": "PASS", "measured": 0, "note": "measured 0"},
            {"name": "model run: CONTRADICTED recall", "metric": "y", "op": ">=", "value": None, "applies_to": "model_run",
             "status": "NOT APPLICABLE", "measured": None, "note": "needs a live model run"},
        ],
        "failed_cases": [{"record_id": c.record_id, "expected": c.expected, "predicted": c.predicted, "outcome": c.outcome,
                          "reason": c.reason} for c in CASES.values() if c.outcome != "correct"],
        "cases": {"records": 7, "replay_misses": None, "reasons": {"claim error: PROVIDER_TIMEOUT": 1}},
        "corrections": {"live": None}, "extraction": {"live": None},
    }
    for path, value in changes.items():
        node = report
        *parents, last = path.split("__")
        for key in parents:
            node = node[key]
        node[last] = value
    return report


# --- Successful generation ------------------------------------------------------------------------------


def test_every_required_section_is_rendered_from_the_result():
    text = rep.render_markdown(fixture_report())
    for n in range(1, 21):
        assert f"## {n}. " in text, n
    assert "TP 2 · FP 1 · FN 2 · TN 3" in text and "66.7% (2/3)" in text  # numbers come from the result
    assert "| Retrieval recall@5 | 100.0% (6/6) |" in text and "oracle/gold-labels" in text
    assert "decision-policy-v1" in text and "not calibrated" in text and '"top_k": 5' in text


def test_passed_gated_outcomes_and_wrong_approvals_are_explained():
    text = rep.render_markdown(fixture_report(gates=[]))
    assert "**Outcome: PASSED.**" in text and "this pass says nothing about model accuracy" in text
    assert "**Wrong approvals** (predicted SUPPORTED on another label): 1" in text
    assert "**missed contradictions** (CONTRADICTED predicted as anything else): 2" in text


# --- Undefined versus measured zero ---------------------------------------------------------------------


def test_undefined_metrics_are_unavailable_and_measured_zero_is_zero():
    report = fixture_report()
    report["required_metrics"]["correction_traceability"] = None
    report["required_metrics"]["unavailable"]["correction_traceability"] = "no correction was proposed"
    report["required_metrics"]["false_positive_rate"] = {"numerator": 0, "denominator": 4, "value": 0.0}
    text = rep.render_markdown(report)
    assert "| Correction traceability | unavailable (no correction was proposed) |" in text
    assert "| False-positive rate | 0.0% (0/4) |" in text
    assert "0.0% (0/0)" not in text


# --- Failed, partial, incomplete, skipped ----------------------------------------------------------------


def test_a_failed_gate_fails_the_run_and_is_marked_violated():
    report = fixture_report()
    assert rep.outcome(report) == {"status": "failed", "reasons": ["gate failed: oracle: CONTRADICTED recall (engine ceiling)"]}
    [row] = [r for r in rep.baseline_rows(report) if r["name"].startswith("oracle")]
    assert row["violated"] and row["enforced"] and row["change"] == pytest.approx(-0.5)
    assert "| oracle: CONTRADICTED recall (engine ceiling) | oracle | 0.5 | >= 1 | -0.5 | FAIL |" in rep.render_markdown(report)


def test_a_partial_run_keeps_its_results_and_says_why_it_failed():
    report = fixture_report(run__evaluation_failed=True, gates=[])
    report["cases"]["replay_misses"] = 12
    text = rep.render_markdown(report)
    assert "**Outcome: FAILED.**" in text and "no record received a verdict" in text
    assert "## 11. Required metrics" in text and "Replay misses: 12" in text  # partial results not hidden
    assert "claim error: PROVIDER_TIMEOUT" in text


def test_an_incomplete_run_is_reported_with_its_error_and_no_metrics():
    report = {"run": {"created_at": "2026-10-24T10:20:30+00:00", "incomplete": True, "verdict_source": "openrouter",
                      "error": "ProviderNotConfiguredError: set OPENROUTER_API_KEY and INKLOOM_LLM_MODELS"}}
    assert rep.outcome(report)["status"] == "incomplete"
    text = rep.render_markdown(report)
    assert "**Outcome: INCOMPLETE.**" in text and "No metrics are reported" in text and "## 11." not in text
    assert incomplete_summary(report).state == "incomplete"


def test_skipped_checks_are_listed_and_never_counted_as_passed():
    report = fixture_report()
    text = rep.render_markdown(report)
    assert "- Skipped gate (NOT APPLICABLE): model run: CONTRADICTED recall: needs a live model run" in text
    assert "- Live corrector: not run (no live model)." in text and "- Live extraction: not run (no live model)." in text
    assert "1 gate(s) did not apply" not in text  # the run failed; skipped gates do not make it pass


def test_missing_model_metadata_says_not_recorded():
    report = fixture_report(run__model_configuration=None, run__prompt_versions=None, run__retrieval_parameters=None)
    report["verdicts"]["model_ids"] = []
    text = rep.render_markdown(report)
    assert "Model identifiers that answered: not recorded" in text and "Provider: none (no provider in this run)" in text
    assert "## 9. Retrieval configuration\n\n- not recorded" in text and "- Configured: not recorded" in text


def test_citation_failures_are_listed_by_cause():
    text = rep.render_markdown(fixture_report())
    assert "5 citations; failures by cause: {'does_not_resolve:quote_mismatch': 1, 'no_supporting_evidence_exists': 1}" in text


def test_no_baseline_is_shown_as_no_baseline_with_how_to_set_one():
    text = rep.render_markdown(fixture_report())
    assert "| model run: CONTRADICTED recall | model_run | — | no baseline | — | NOT APPLICABLE |" in text
    assert "To set one: measure it in a real run" in text


# --- Invalid results --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("bad", "message"), [
    ([], "must be an object"),
    ({}, "no 'run'"),
    ({"run": {"created_at": "2026-10-24T10:20:30+00:00"}}, "no 'run/verdict_source'"),
    ({"run": {"created_at": "2026-10-24T10:20:30+00:00", "incomplete": True}}, "no 'run/error'"),
], ids=["not-an-object", "no-run", "no-source", "incomplete-without-error"])
def test_invalid_results_are_refused(bad, message):
    with pytest.raises(rep.ReportInputError, match=message):
        rep.render_markdown(bad)


def test_a_metric_that_is_not_a_ratio_is_refused_and_nothing_is_written(tmp_path):
    report = fixture_report()
    report["required_metrics"]["contradicted_recall"] = 0.5
    with pytest.raises(rep.ReportInputError, match="not a ratio"):
        rep.write_report(report, tmp_path)
    assert list(tmp_path.iterdir()) == []


# --- Timestamped paths ------------------------------------------------------------------------------------


def test_reports_are_named_by_their_utc_timestamp_and_never_overwritten(tmp_path):
    assert rep.report_stem("2026-10-24T10:20:30+00:00") == "20261024T102030Z"
    cases = tmp_path / "cases.jsonl"
    cases.write_text("{}\n", encoding="utf-8")
    first = rep.write_report(fixture_report(), tmp_path / "reports", cases, {"state": "x"})
    second = rep.write_report(fixture_report(), tmp_path / "reports")
    assert first["markdown"].name == "20261024T102030Z.md" and second["markdown"].name == "20261024T102030Z-2.md"
    assert {p.name for p in first.values()} == {"20261024T102030Z.md", "20261024T102030Z.json", "20261024T102030Z.cases.jsonl",
                                                "20261024T102030Z.summary.json"}
    stored = json.loads(first["json"].read_text(encoding="utf-8"))
    assert stored["report_schema"] == "evaluation-report-v1" and stored["report_id"] == "20261024T102030Z"
    assert rep.render_markdown(stored) == first["markdown"].read_text(encoding="utf-8")  # re-rendered identically


# --- The Trust Scorecard summary contract ------------------------------------------------------------------


def test_the_summary_carries_the_eight_metrics_and_real_cases_of_each_status():
    summary = build_summary(fixture_report(), CASES, RECORDS)
    assert [m.key for m in summary.metrics] == [k for k, _, _ in rep.METRICS]
    assert summary.source["is_model_quality"] is False and summary.source["production_statistics"] is False
    assert summary.outcome["status"] == "failed"
    statuses = {c.expected for c in summary.cases}
    assert statuses == {"SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE"}
    assert all(c.record_id in CASES and c.content == RECORDS[c.record_id].claim_text for c in summary.cases)  # real records only
    disagreements = [c for c in summary.cases if not c.agrees]
    assert disagreements  # a disagreement is shown first when the label has one
    v1_009 = next(c for c in summary.cases if c.expected == "SUPPORTED")
    assert v1_009.record_id == "v1-009" and v1_009.predicted == "CONTRADICTED"


def test_summary_citations_report_resolution_and_support_separately():
    from inkloom_verify.evaluation.summary import case_out

    [good] = case_out(RECORDS["v1-027"], CASES["v1-027"]).citations  # the gold price quote, right verdict
    assert good.resolves and good.supports
    [nothing] = case_out(RECORDS["v1-037"], CASES["v1-037"]).citations  # a real quote, but the record has no supporting evidence
    assert nothing.resolves and not nothing.supports


def test_latest_summary_states(tmp_path):
    assert isinstance(latest_summary(tmp_path / "missing"), NoEvaluation)
    reports = tmp_path / "reports"
    summary = build_summary(fixture_report(), CASES, RECORDS).model_dump(mode="json")
    rep.write_report(fixture_report(), reports, None, summary)
    loaded = latest_summary(reports)
    assert isinstance(loaded, EvaluationSummary) and loaded.report_id == "20261024T102030Z" and loaded.stale is False
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"files": {"eval/dataset.jsonl": {"sha256": "0" * 64}}}), encoding="utf-8")
    assert latest_summary(reports, lock).stale is True  # the dataset changed after this run
    later = fixture_report(run__created_at="2026-10-25T08:00:00+00:00", run__incomplete=True, run__error="X: boom")
    rep.write_report(later, reports, None, incomplete_summary(later).model_dump(mode="json"))
    assert isinstance(latest_summary(reports), IncompleteEvaluation)  # the newest run stopped: shown, not hidden
    (reports / "20261026T000000Z.summary.json").write_text('{"contract": "evaluation-summary-v1", "state": "available"}', encoding="utf-8")
    with pytest.raises(SummaryInvalid):
        latest_summary(reports)
