"""Evaluation reports: Markdown and JSON written for every run under ``eval/reports/`` (EVAL.md Phase 7).

``render_markdown(report)`` turns the runner's actual output (the ``report.json`` dictionary) into
a readable report with the sections EVAL.md requires. Nothing is computed twice: every number comes
from the runner; this module only formats it, decides the run's outcome, and refuses malformed input.

Outcome, decided here once and shown everywhere:

* ``incomplete``: the run stopped before it finished (an invalid input, a missing provider, an
  unexpected error). Whatever was recorded is kept, with the error.
* ``failed``: the run finished but a regression gate failed, or no record received a verdict.
* ``passed``: the run finished and no applicable gate failed. Gates that do not apply to this kind
  of run are listed as skipped, never as passed. A pass on scripted answers says nothing about a
  live model, and the report says so.

Missing metrics are "unavailable (reason)", never 0: a measured zero and an undefined value are
different results.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from inkloom_verify.evaluation.limitations import LIMITATIONS

REPORT_SCHEMA = "evaluation-report-v1"
_SOURCES = {
    "oracle": "scripted gold answers through the full pipeline: the engine's ceiling, **not model quality**",
    "abstain": "a floor that always answers NOT_ENOUGH_EVIDENCE: **not model quality**",
    "dry-run": "an offline stub that counts calls: **not model quality**",
    "openrouter": "the live model",
    "replay": "replayed provider answers from a recorded cassette",
    "predictions": "saved predictions from an earlier run",
}
METRICS = [  # (key in required_metrics, label, what it answers)
    ("contradicted_precision", "Precision (CONTRADICTED)", "Of the claims flagged CONTRADICTED, how many really are."),
    ("contradicted_recall", "Recall (CONTRADICTED)", "Of the claims that really are CONTRADICTED, how many were flagged."),
    ("false_positive_rate", "False-positive rate", "Of the claims that are not CONTRADICTED, how many were wrongly flagged."),
    ("false_negative_rate", "False-negative rate", "Of the claims that are CONTRADICTED, how many were missed."),
    ("citation_validity", "Citation validity", "Citations that quote the reference exactly and support the right verdict."),
    ("retrieval_recall_at_5", "Retrieval recall@5", "Claims whose annotated evidence is among the 5 passages retrieved."),
    ("human_review_share", "Share routed to human review", "Records sent to a person instead of cleared automatically."),
    ("correction_traceability", "Correction traceability", "Proposed corrections whose every added word is in the cited evidence."),
]


class ReportInputError(ValueError):
    """The runner's output is missing something a report needs, or has the wrong shape."""


def _require(report: dict[str, Any], path: str) -> Any:
    node: Any = report
    for key in path.split("/"):
        if not isinstance(node, dict) or key not in node:
            raise ReportInputError(f"evaluation result has no '{path}'")
        node = node[key]
    return node


def validate(report: Any) -> None:
    """Raises ReportInputError if ``report`` cannot be reported faithfully."""
    if not isinstance(report, dict):
        raise ReportInputError("evaluation result must be an object")
    run = _require(report, "run")
    _require(report, "run/created_at")
    if run.get("incomplete"):
        _require(report, "run/error")
        return
    for path in ("run/verdict_source", "run/dataset", "verdicts/confusion", "verdicts/examples", "required_metrics/counts",
                 "required_metrics/unavailable", "gates"):
        _require(report, path)
    for key, _, _ in METRICS:
        value = _require(report, f"required_metrics/{key}")
        if value is not None and not (isinstance(value, dict) and {"numerator", "denominator", "value"} <= set(value)):
            raise ReportInputError(f"metric '{key}' is not a ratio")
    if not isinstance(report["gates"], list):
        raise ReportInputError("gates must be a list")


def outcome(report: dict[str, Any]) -> dict[str, Any]:
    """{"status": passed | failed | incomplete, "reasons": [...]} for this run."""
    run = report.get("run", {})
    if run.get("incomplete"):
        return {"status": "incomplete", "reasons": [f"the run stopped: {run.get('error', 'unknown error')}"]}
    reasons = []
    if run.get("evaluation_failed"):
        reasons.append("no record received a verdict")
    failed = [g["name"] for g in report.get("gates", []) if g.get("status") == "FAIL"]
    reasons += [f"gate failed: {name}" for name in failed]
    if reasons:
        return {"status": "failed", "reasons": reasons}
    skipped = sum(1 for g in report.get("gates", []) if g.get("status") in ("NOT APPLICABLE", "NOT ENFORCED"))
    note = [f"{skipped} gate(s) did not apply or have no baseline (listed under skipped checks)"] if skipped else []
    if not report.get("verdicts", {}).get("is_model_quality"):
        note.append("no live model answered: this pass says nothing about model accuracy")
    return {"status": "passed", "reasons": note}


def describe_source(report: dict[str, Any]) -> str:
    """What answered, from the provider that actually answered (REG-008), not the flag alone."""
    run, source = report["run"], report["run"]["verdict_source"]
    provider = (run.get("model_configuration") or {}).get("provider")
    if source in ("openrouter", "replay") and not report["verdicts"].get("is_model_quality"):
        return f"provider '{provider or 'unknown'}', not a live model: **not model quality**"
    return _SOURCES.get(source, source)


def _ratio(r: dict[str, Any] | None, reason: str | None = None) -> str:
    if r is None or r.get("value") is None:
        return f"unavailable ({reason})" if reason else "unavailable"
    return f"{r['value']:.1%} ({r['numerator']}/{r['denominator']})"


def _value(v: Any) -> str:
    return "—" if v is None else (f"{v:.4g}" if isinstance(v, float) else str(v))


def _fmt_config(value: Any) -> str:
    return "not recorded" if value in (None, {}, []) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def baseline_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per gate: current value, baseline value, absolute change, enforced, status."""
    rows = []
    for g in report.get("gates", []):
        current, baseline = g.get("measured"), g.get("value")
        change = current - baseline if isinstance(current, (int, float)) and isinstance(baseline, (int, float)) else None
        rows.append({"name": g["name"], "applies_to": g.get("applies_to"), "op": g.get("op"), "current": current,
                     "baseline": baseline, "change": change, "status": g.get("status"),
                     "enforced": g.get("status") in ("PASS", "FAIL"), "violated": g.get("status") == "FAIL",
                     "note": g.get("note", "")})
    return rows


def render_markdown(report: dict[str, Any], max_cases: int = 25) -> str:
    validate(report)
    run = report["run"]
    out = outcome(report)
    lines = [f"# Evaluation report {run['created_at']}", ""]

    if run.get("incomplete"):
        lines += ["## 1. Run summary", "", f"**Outcome: INCOMPLETE.** {out['reasons'][0]}", "",
                  "No metrics are reported for an incomplete run; nothing was measured after the error.", "",
                  "## 2. Execution", "", f"- Timestamp: {run['created_at']}",
                  f"- Requested source: {run.get('verdict_source', 'unknown')}",
                  f"- Engine {run.get('engine_version', '?')} · Python {run.get('python', '?')} · commit {run.get('git_commit') or 'unknown'}",
                  "", "## 20. Errors, unavailable metrics and skipped checks", "", f"- Error: {run['error']}", ""]
        return "\n".join(lines)

    v, m, ds = report["verdicts"], report["required_metrics"], run["dataset"]
    lines += ["## 1. Run summary", "",
              f"**Outcome: {out['status'].upper()}.** Answers came from {describe_source(report)}.",
              *[f"- {r}" for r in out["reasons"]], "",
              "## 2. Execution", "",
              f"- Timestamp: {run['created_at']}",
              f"- Engine {run.get('engine_version')} · Python {run.get('python')} · commit {run.get('git_commit') or 'unknown'}"
              + (" (uncommitted changes)" if run.get("git_dirty") else ""),
              f"- Pipeline: {run.get('pipeline') or 'none (no provider)'}", "",
              "## 3. Outcome", "", f"**{out['status']}**", *[f"- {r}" for r in out["reasons"]], "",
              "## 4. Dataset", "",
              f"- {ds.get('path')} · sha256 `{ds.get('sha256')}`" + ("" if ds.get("locked") else " · **not the locked dataset**"),
              f"- Human-reviewed labels: {report.get('datasets', {}).get('human_reviewed', 'unknown')}/{ds.get('records')}", "",
              "## 5. Size and class distribution", "",
              f"- {ds.get('records')} records evaluated: {v['examples']}"]
    labels = ds.get("labels") or {}
    if labels:
        lines.append("- Labels: " + ", ".join(f"{k} {n}" for k, n in labels.items()))
    if ds.get("groups"):
        lines.append("- Groups (EVAL.md mix): " + ", ".join(f"{k} {n}" for k, n in ds["groups"].items()))
    config = run.get("model_configuration") or {}
    lines += ["", "## 6. Model", "", f"- Model identifiers that answered: {', '.join(v.get('model_ids') or []) or 'not recorded'}",
              f"- Configured models: {_fmt_config(config.get('models'))}", "",
              "## 7. Provider", "", f"- Provider: {config.get('provider', 'none (no provider in this run)')}",
              f"- Configuration: {_fmt_config({k: x for k, x in config.items() if k not in ('provider', 'models')})}", "",
              "## 8. Prompt versions", "", f"- Configured: {_fmt_config(run.get('prompt_versions'))}",
              f"- Actually sent by the verifier: {', '.join(v.get('prompt_versions_sent') or []) or 'none'}", "",
              "## 9. Retrieval configuration", "", f"- {_fmt_config(run.get('retrieval_parameters'))}", "",
              "## 10. Decision thresholds and policy", ""]
    policy = (run.get("decision_policy") or {}).get("policy") or {}
    calibration = (run.get("decision_policy") or {}).get("calibration") or {}
    lines += [f"- Policy {policy.get('version', 'not recorded')}: {_fmt_config(policy.get('thresholds'))}",
              f"- Calibration: {calibration.get('status', 'not recorded')} (split {calibration.get('split', '?')})",
              f"- Uses model confidence: {policy.get('uses_model_confidence', 'not recorded')}", "",
              "## 11. Required metrics (positive class: CONTRADICTED)", "",
              f"TP {m['counts'].get('tp')} · FP {m['counts'].get('fp')} · FN {m['counts'].get('fn')} · TN {m['counts'].get('tn')} · "
              f"missing predictions {m['counts'].get('missing_predictions')} · ERROR predictions {m['counts'].get('error_predictions')}", "",
              "| Metric | Value | What it answers |", "|---|---|---|"]
    lines += [f"| {label} | {_ratio(m.get(key), m['unavailable'].get(key))} | {what} |" for key, label, what in METRICS]
    lines += [f"| Citation resolution (quote found verbatim) | {_ratio(m.get('citation_resolution'), m['unavailable'].get('citation_resolution'))} "
              "| Citations that quote the reference exactly. |",
              f"| Provider failure rate | {_ratio(m.get('provider_failure_rate'), m['unavailable'].get('provider_failure_rate'))} "
              "| Records whose answer was ERROR (provider failure, invalid output, budget refusal, missing). |"]
    latency = m.get("latency") or {}
    lines += ["", (f"Latency per case (wall clock, seconds; includes provider time only for live runs): n {latency['n']} · "
                   f"mean {latency['mean_seconds']} · p50 {latency['p50_seconds']} · p95 {latency['p95_seconds']} · "
                   f"max {latency['max_seconds']}") if latency else
              f"Latency per case: unavailable ({m['unavailable'].get('latency', 'not measured')})", "",
              "## 12. Confusion matrix", "", "Rows are labels, columns are predictions.", ""]
    confusion = v["confusion"]
    columns = list(next(iter(confusion.values())).keys()) if confusion else []
    lines += ["| label \\ prediction | " + " | ".join(columns) + " |", "|---|" + "---|" * len(columns)]
    lines += [f"| {g} | " + " | ".join(str(row[c]) for c in columns) + " |" for g, row in confusion.items()]
    lines += ["", "**Wrong approvals** (predicted SUPPORTED on another label): "
              f"{sum(row.get('SUPPORTED', 0) for g, row in confusion.items() if g != 'SUPPORTED')} · "
              "**missed contradictions** (CONTRADICTED predicted as anything else): "
              f"{sum(n for p, n in confusion.get('CONTRADICTED', {}).items() if p != 'CONTRADICTED')}", "",
              "## 13. Failed evaluation cases", ""]
    failed = report.get("failed_cases")
    if failed is None:
        lines.append(f"No per-case outcomes in this run (no pipeline). Failure counts: {v.get('failure_counts') or 'none'}")
    elif not failed:
        lines.append("None: every record received its gold label.")
    else:
        lines += ["| Record | Expected | Predicted | Outcome | Reason |", "|---|---|---|---|---|"]
        lines += [f"| {c['record_id']} | {c['expected']} | {c['predicted']} | {c['outcome']} | {c.get('reason') or ''} |"
                  for c in failed[:max_cases]]
        if len(failed) > max_cases:
            lines.append(f"\n… and {len(failed) - max_cases} more in the cases file.")
    cf = {k: n for k, n in m.get("citation_failures", {}).items() if k not in ("citations", "valid", "resolved")}
    retr = m.get("retrieval", {})
    lines += ["", "## 14. Citation-validation failures", "",
              f"{m.get('citation_failures', {}).get('citations', 0)} citations; failures by cause: {cf or 'none'}", "",
              "## 15. Retrieval misses", "",
              f"{retr.get('with_gold_evidence', '?')} records with annotated evidence, {retr.get('excluded_without_gold_evidence', '?')} "
              f"excluded (none annotated); empty retrievals {retr.get('empty_results', '?')}; misses: {retr.get('misses') or 'none'}", "",
              "## 16. Human-review routing", ""]
    review = m.get("review") or {}
    if review:
        lines += [f"- Routed: {_ratio(m.get('human_review_share'))}; by label {review.get('routed_by_label')}",
                  f"- Cleared without review: {review.get('auto_cleared')}; of those not labelled SUPPORTED: "
                  f"{review.get('auto_cleared_but_not_supported') or 'none'}",
                  f"- Excluded (no outcome): {review.get('excluded_without_outcome')}"]
    else:
        lines.append(f"Unavailable: {m['unavailable'].get('human_review_share', 'no outcomes')}")
    corr = m.get("corrections") or {}
    lines += ["", "## 17. Correction traceability", ""]
    lines.append(f"- Traceable: {_ratio(m.get('correction_traceability'), m['unavailable'].get('correction_traceability'))}; "
                 f"attempts {corr.get('attempts_by_status') or 'none'}; untraceable {corr.get('untraceable') or 'none'}"
                 if corr else f"Unavailable: {m['unavailable'].get('correction_traceability', 'no outcomes')}")
    lines += ["", "## 18. Comparison with the agreed baseline (eval/baseline.json)", "",
              "| Gate | Applies to | Current | Baseline | Change | Status |", "|---|---|---|---|---|---|"]
    for row in baseline_rows(report):
        baseline = "no baseline" if row["baseline"] is None else f"{row['op']} {_value(row['baseline'])}"
        lines.append(f"| {row['name']} | {row['applies_to']} | {_value(row['current'])} | {baseline} | {_value(row['change'])} | {row['status']} |")
    lines += ["", "A gate with no baseline is not enforced. To set one: measure it in a real run, record the run in "
              "eval/baseline.json `measured_run`, and set the value to the measurement (EVAL.md, Regression testing and CI).", "",
              "## 19. Known limitations", ""]
    lines += [f"- **{lim.topic}** ({lim.status.replace('_', ' ')}): {lim.finding}" for lim in LIMITATIONS]
    lines += ["", "## 20. Errors, unavailable metrics and skipped checks", ""]
    lines += [f"- Unavailable metric `{k}`: {why}" for k, why in m["unavailable"].items()] or ["- No unavailable metrics."]
    lines += [f"- Skipped gate ({g['status']}): {g['name']}: {g.get('note', '')}" for g in report["gates"]
              if g.get("status") in ("NOT APPLICABLE", "NOT ENFORCED")]
    if report.get("corrections", {}).get("live") is None:
        lines.append("- Live corrector: not run (no live model).")
    if report.get("extraction", {}).get("live") is None:
        lines.append("- Live extraction: not run (no live model).")
    cases = report.get("cases") or {}
    if cases.get("replay_misses"):
        lines.append(f"- Replay misses: {cases['replay_misses']} requests had no recording and became errors.")
    if cases.get("reasons"):
        lines.append(f"- Errors and skipped records: {cases['reasons']}")
    lines += ["", "## Appendix: deterministic sections", ""]
    for name, entry in (report.get("retrieval") or {}).items():
        lines.append(f"- Retrieval {name}: @1 {_ratio(entry.get('recall_at_1'))}, @3 {_ratio(entry.get('recall_at_3'))}, "
                     f"@5 {_ratio(entry.get('recall_at_5'))}")
    checker = (report.get("corrections") or {}).get("checker")
    if checker:
        lines.append(f"- Correction checks: bad edits rejected {_ratio(checker['correctly_rejected'])}, good accepted "
                     f"{_ratio(checker['correctly_accepted'])}, false accepts {checker['false_accepts']}")
    extraction = report.get("extraction") or {}
    for name, entry in [("oracle", extraction.get("oracle"))] + list((extraction.get("adversaries") or {}).items()):
        if entry:
            lines.append(f"- Extraction (deterministic), {name}: recall {_ratio(entry.get('claim_recall'))}, exact spans "
                         f"{_ratio(entry.get('exact_span_matches'))}, not atomic {entry.get('atomicity_violations')}, "
                         f"opinions {entry.get('opinion_leakage')}, unsafe rewordings {entry.get('statements_changed_unsafely')}")
    for name, e in (report.get("enforcement") or {}).items():
        lines.append(f"- Enforcement (verifier only), {name}: accepted {e.get('accepted')}, quotes not in any source "
                     f"{e.get('accepted_quotes_not_in_any_source')}, false-SUPPORTED {_ratio(e.get('false_supported'))}")
    for name, ps in (report.get("pipeline_safety") or {}).items():
        lines.append(f"- Pipeline safety, {name}: predicted {ps['predicted']}; non-SUPPORTED auto-cleared "
                     f"{ps['auto_cleared_not_supported']}; citation resolution {_value(ps['citation_resolution'])}")
    if report.get("faults"):
        lines.append(f"- Fault cases handled: {_ratio(report['faults']['pass_rate'])}")
    return "\n".join(lines) + "\n"


def report_stem(created_at: str) -> str:
    """'2026-10-24T10:20:30+00:00' -> '20261024T102030Z' (UTC, sortable, filesystem-safe)."""
    return datetime.fromisoformat(created_at).strftime("%Y%m%dT%H%M%SZ")


def unique_stem(directory: Path, stem: str) -> str:
    """``stem``, or ``stem-2``, ``stem-3``... if a report with that name already exists: never overwrite."""
    candidate, n = stem, 1
    while any(directory.glob(f"{candidate}.*")):
        n += 1
        candidate = f"{stem}-{n}"
    return candidate


def write_report(report: dict[str, Any], directory: Path, cases_file: Path | None = None,
                 summary: dict[str, Any] | None = None) -> dict[str, Path]:
    """Writes <stem>.md, <stem>.json and, when given, <stem>.cases.jsonl and <stem>.summary.json."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = unique_stem(directory, report_stem(report["run"]["created_at"]))
    text = render_markdown(report)  # validates first: nothing is written for an invalid result
    paths = {"markdown": directory / f"{stem}.md", "json": directory / f"{stem}.json"}
    paths["markdown"].write_text(text, encoding="utf-8", newline="\n")
    stored = report | {"report_schema": REPORT_SCHEMA, "report_id": stem}
    paths["json"].write_text(json.dumps(stored, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    if cases_file is not None and cases_file.exists():
        paths["cases"] = directory / f"{stem}.cases.jsonl"
        paths["cases"].write_bytes(cases_file.read_bytes())
    if summary is not None:
        paths["summary"] = directory / f"{stem}.summary.json"
        paths["summary"].write_text(json.dumps(summary | {"report_id": stem}, indent=2, ensure_ascii=False) + "\n",
                                    encoding="utf-8", newline="\n")
    return paths
