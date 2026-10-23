"""eval/run_eval.py: the report, the label lock, and the regression gates CI relies on."""

import importlib.util
import json
from pathlib import Path

import pytest

from inkloom_verify.evaluation.runner import load_records

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)


@pytest.fixture(scope="module")
def default_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("run")
    code = run_eval.main(["--out", str(out), "--check-baseline"])
    return code, json.loads((out / "report.json").read_text(encoding="utf-8")), (out / "report.md").read_text(encoding="utf-8")


def write_baseline(tmp_path, gates) -> Path:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"gates": gates}), encoding="utf-8")
    return path


def gate(metric, op, value, applies_to="always"):
    return {"name": metric, "metric": metric, "op": op, "value": value, "applies_to": applies_to}


# --- The default (CI) run ----------------------------------------------------------------------


def test_default_run_passes_its_gates_and_writes_both_reports(default_run):
    code, report, text = default_run
    assert code == 0
    statuses = {g["name"]: g["status"] for g in report["gates"]}
    assert all(s == "PASS" for g, s in statuses.items() if "(model run)" not in g)
    assert {s for g, s in statuses.items() if "(model run)" in g} == {"NOT APPLICABLE"}
    for section in ("## Verdicts", "## Retrieval recall@k", "## Corrections", "## Enforcement", "## Error handling",
                    "## Regression gates"):
        assert section in text


def test_the_abstain_floor_is_never_presented_as_model_accuracy(default_run):
    _, report, text = default_run
    assert report["verdicts"]["source"] == "abstain" and report["verdicts"]["is_model_quality"] is False
    assert "not model accuracy" in text and "Human-reviewed labels in eval/dataset.jsonl: 0/55" in text


def test_report_has_every_required_metric(default_run):
    _, report, _ = default_run
    v = report["verdicts"]
    assert v["examples"] == 55
    assert set(v["per_class"]) == {"SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE"}
    assert set(v["confusion"]["CONTRADICTED"]) == {"SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE", "ERROR"}
    for key in ("accuracy", "abstention_rate", "citation_validity", "false_supported_rate"):
        assert {"numerator", "denominator", "value"} <= set(v[key])
    assert report["retrieval"]["dataset.jsonl"]["recall_at_5"]["denominator"] == 37
    assert report["faults"]["pass_rate"] == {"numerator": 18, "denominator": 18, "value": 1.0}


# --- Gates fail when they should ---------------------------------------------------------------


def test_a_regression_below_a_deterministic_baseline_fails(tmp_path):
    baseline = write_baseline(tmp_path, [gate("corrections/checker/correctly_accepted", ">=", 1.0)])  # measured 17/18
    assert run_eval.main(["--out", str(tmp_path / "out"), "--check-baseline", str(baseline)]) == 1
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["gates"][0]["status"] == "FAIL"


def test_an_unknown_metric_is_an_input_error_not_a_pass(tmp_path, capsys):
    baseline = write_baseline(tmp_path, [gate("retrieval.dataset.jsonl.recall_at_5", ">=", 1.0)])
    assert run_eval.main(["--out", str(tmp_path / "out"), "--check-baseline", str(baseline)]) == 2
    assert "does not exist" in capsys.readouterr().err


def predictions(tmp_path, name, change=None) -> Path:
    """Replayable predictions for eval/dataset.jsonl: the labels and gold quotes, optionally altered."""
    lines = []
    for record in load_records(ROOT / "eval" / "dataset.jsonl"):
        p = {"record_id": record.record_id, "verdict": record.expected_verdict.value, "model_id": "replay/test",
             "citations": [{"doc_id": g.doc_id, "quote": g.quote, "quote_span": {"start": g.span.start, "end": g.span.end}}
                           for g in record.gold_evidence]}
        if change:
            change(record, p)
        lines.append(json.dumps(p))
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


MODEL_GATES = [
    gate("verdicts/citation_validity", ">=", 1.0, "model_run"),
    gate("verdicts/per_class/CONTRADICTED/recall", ">=", 0.9, "model_run"),
]


def test_model_run_gates_pass_for_a_good_replay(tmp_path):
    baseline = write_baseline(tmp_path, MODEL_GATES)
    good = predictions(tmp_path, "good.jsonl")
    assert run_eval.main(["--predictions", str(good), "--out", str(tmp_path / "o"), "--check-baseline", str(baseline)]) == 0


def test_contradicted_recall_below_threshold_fails_ci(tmp_path):
    def miss_contradictions(record, p):
        if p["verdict"] == "CONTRADICTED":
            p.update(verdict="NOT_ENOUGH_EVIDENCE", citations=[])

    baseline = write_baseline(tmp_path, MODEL_GATES)
    bad = predictions(tmp_path, "bad.jsonl", miss_contradictions)
    assert run_eval.main(["--predictions", str(bad), "--out", str(tmp_path / "o"), "--check-baseline", str(baseline)]) == 1


def test_citation_validity_below_baseline_fails_ci(tmp_path):
    def fabricate(record, p):
        for citation in p["citations"]:
            citation["quote"] = citation["quote"][:-1] + "X"

    baseline = write_baseline(tmp_path, MODEL_GATES)
    bad = predictions(tmp_path, "fabricated.jsonl", fabricate)
    assert run_eval.main(["--predictions", str(bad), "--out", str(tmp_path / "o"), "--check-baseline", str(baseline)]) == 1


def test_unset_model_thresholds_are_reported_not_enforced(tmp_path):
    baseline = write_baseline(tmp_path, [gate("verdicts/citation_validity", ">=", None, "model_run")])
    good = predictions(tmp_path, "good.jsonl")
    assert run_eval.main(["--predictions", str(good), "--out", str(tmp_path / "o"), "--check-baseline", str(baseline)]) == 0
    report = json.loads((tmp_path / "o" / "report.json").read_text(encoding="utf-8"))
    assert report["gates"][0]["status"] == "NOT ENFORCED"


# --- Labels cannot change silently -------------------------------------------------------------


def test_the_lock_matches_every_evaluation_input():
    lock = json.loads((ROOT / "eval" / "datasets.lock.json").read_text(encoding="utf-8"))
    assert run_eval.check_lock(lock) == []
    for name, entry in lock["files"].items():
        assert run_eval.lock_entry(ROOT / name) == entry  # hashes, record counts and label counts


def test_a_changed_label_stops_the_run(tmp_path, monkeypatch, capsys):
    lock = json.loads((ROOT / "eval" / "datasets.lock.json").read_text(encoding="utf-8"))
    lock["files"]["eval/dataset.jsonl"]["sha256"] = "0" * 64  # as if a label had been edited
    fake = tmp_path / "lock.json"
    fake.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(run_eval, "LOCK", fake)
    assert run_eval.main(["--out", str(tmp_path / "out")]) == 2
    assert "label lock mismatch" in capsys.readouterr().err


def test_lock_hashes_ignore_line_endings(tmp_path):
    lf, crlf = tmp_path / "lf.json", tmp_path / "crlf.json"
    lf.write_bytes(b'{"a": 1}\n{"b": 2}\n')
    crlf.write_bytes(b'{"a": 1}\r\n{"b": 2}\r\n')
    assert run_eval.sha256(lf) == run_eval.sha256(crlf)


def test_live_run_without_credentials_fails_clearly(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("INKLOOM_LLM_MODELS", raising=False)
    assert run_eval.main(["--verdicts", "openrouter", "--out", str(tmp_path / "out")]) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err


# --- The dataset -------------------------------------------------------------------------------


def test_dataset_keeps_every_v1_record_unchanged():
    v1 = [line for line in (ROOT / "eval/data/verification_v1.jsonl").read_text(encoding="utf-8").splitlines() if line]
    dataset = [line for line in (ROOT / "eval/dataset.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assert dataset[: len(v1)] == v1


def test_dataset_covers_the_required_cases():
    records = load_records(ROOT / "eval" / "dataset.jsonl")
    categories = {c.value for r in records for c in r.categories}
    assert {"numeric", "date", "named_entity", "ambiguous", "conflicting_evidence", "prompt_injection", "compound"} <= categories
    conflicts = [r for r in records if "conflicting_evidence" in {c.value for c in r.categories}]
    assert [r.expected_verdict.value for r in conflicts].count("NOT_ENOUGH_EVIDENCE") == 4
    assert all(r.label_rationale for r in records)
    assert all(r.gold_evidence for r in records if r.expected_verdict.value != "NOT_ENOUGH_EVIDENCE")


def test_fault_cases_cover_every_stage_and_fault():
    cases = json.loads((ROOT / "eval" / "fault_cases.json").read_text(encoding="utf-8"))
    assert {(c["stage"], c["fault"]) for c in cases} == {
        (s, f) for s in ("extraction", "verification", "correction")
        for f in ("timeout", "rate_limit", "unavailable", "malformed_json", "schema_invalid", "not_configured")
    }


def test_report_includes_the_extraction_evaluation_and_its_gates(default_run):
    _, report, text = default_run
    ex = report["extraction"]
    assert ex["oracle"]["records"] == 24 and ex["oracle"]["labelled_claims"] == 33
    assert ex["oracle"]["exact_span_matches"]["value"] == 1.0 and ex["live"] is None
    statuses = {g["name"]: g["status"] for g in report["gates"]}
    assert statuses["extraction: unsafe rewordings kept (embellisher)"] == "PASS"
    assert statuses["extraction: claim recall (model run)"] == "NOT APPLICABLE"
    assert "## Claim extraction" in text and "Live extraction: not run" in text


# --- Prompt versions, model configuration and call counts (PROMPTS.md Phase 7) -----------------


@pytest.mark.parametrize("prompt_set", sorted(run_eval.PROMPT_SETS))
def test_a_dry_run_pins_and_records_the_prompt_set(tmp_path, prompt_set):
    """Offline: --dry-run answers every call minimally. The report says which prompts were sent
    and never presents the run as model quality."""
    assert run_eval.main(["--verdicts", "openrouter", "--dry-run", "--prompts", prompt_set, "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    expected = run_eval.PROMPT_SETS[prompt_set]
    assert report["run"]["prompt_versions"] == expected and report["run"]["verdict_source"] == "dry-run"
    assert report["verdicts"]["prompt_versions_sent"] == [expected["verify_claim"]]
    assert report["verdicts"]["is_model_quality"] is False
    calls = report["calls"]
    assert set(calls) == {"claim_extraction", "claim_verification", "claim_correction"}
    assert calls["claim_extraction"]["calls"] == 24 and calls["claim_correction"]["calls"] == 19
    assert all(s["repair_calls"] == 0 and s["errors"] == {} for s in calls.values())


def test_the_active_defaults_are_v1_until_a_release_is_approved():
    assert run_eval.active_prompts() == run_eval.PROMPT_SETS["v1"]


def test_dry_run_needs_the_live_source(capsys):
    with pytest.raises(SystemExit):
        run_eval.main(["--dry-run"])
    assert "--dry-run needs --verdicts openrouter" in capsys.readouterr().err


def test_the_model_configuration_is_recorded_without_the_key():
    from inkloom_verify.providers.openrouter import OpenRouterProvider, OpenRouterSettings

    key = "sk-or-v1-PHASE7-TEST-ONLY-NOT-A-REAL-KEY-0000"
    config = run_eval.model_configuration(OpenRouterProvider(OpenRouterSettings(api_key=key, models=["a/b", "c/d"])))
    assert config["models"] == ["a/b", "c/d"] and config["temperature"] == 0.0 and config["seed"] == 0
    assert key not in json.dumps(config) and "api_key" not in config


def test_repair_calls_and_provider_errors_are_counted_per_stage():
    from inkloom_verify.providers.base import JsonCompletionRequest, MalformedOutputError

    replies = iter([{"x": 1}, MalformedOutputError("bad")])

    class Inner:
        name = "inner"

        def sampling(self):
            return {}

        def complete_json(self, request):
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return run_eval.JsonCompletion(data=reply, model="m", attempts=1)

    counting = run_eval.CountingProvider(Inner())
    first = JsonCompletionRequest(system="s", user="u", schema_name="claim_verification", json_schema={})
    counting.complete_json(first)
    with pytest.raises(MalformedOutputError):
        counting.complete_json(first.model_copy(update={"user": "u\n\n" + run_eval.REPAIR_MARKER + " x"}))
    assert counting.stats["claim_verification"] == {"calls": 2, "repair_calls": 1, "input_chars": 2 + (1 + 3 + len(run_eval.REPAIR_MARKER) + 2),
                                                    "errors": {"MALFORMED_MODEL_OUTPUT": 1}}
