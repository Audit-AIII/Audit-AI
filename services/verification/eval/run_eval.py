"""Run every evaluation and write a readable report: ``python eval/run_eval.py --help``.

Run from ``services/verification``. Sections (EVAL.md defines every metric and denominator):

1. Datasets: the label lock (eval/datasets.lock.json) is checked first; a changed dataset stops the run.
2. Verdicts on eval/dataset.jsonl, from one explicit source: ``--verdicts abstain`` (a floor,
   the default), ``--verdicts openrouter`` (the live engine; needs credentials) or
   ``--predictions FILE`` (replay a saved live run).
3. Retrieval recall@1/3/5, separately, on eval/dataset.jsonl and eval/data/retrieval_v1.jsonl.
4. Corrections, separately: the deterministic checks on eval/data/corrections_v1.jsonl, plus the
   live corrector when ``--verdicts openrouter``.
5. Enforcement: scripted adversaries through the real verifier and citation guard.
6. Error handling: eval/fault_cases.json, provider faults injected at each stage.
7. Regression gates from eval/baseline.json (``--check-baseline``): exit 1 if any fails.

Only sections 2 and 4 with a live source say anything about model quality. Sections 3, 5 and 6
are deterministic and need no credentials; CI runs them on every change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from inkloom_verify import __version__  # noqa: E402
from inkloom_verify.chunking import ChunkingConfig  # noqa: E402
from inkloom_verify.evaluation import scripted  # noqa: E402
from inkloom_verify.evaluation.corrections import check_candidates, load_cases, run_live  # noqa: E402
from inkloom_verify.evaluation.metrics import GOLD_CLASSES, PREDICTED_CLASSES  # noqa: E402
from inkloom_verify.evaluation.runner import (  # noqa: E402
    EvaluationInputError,
    _git,
    load_records,
    run,
)
from inkloom_verify.providers.base import ProviderError  # noqa: E402
from inkloom_verify.retrieval import RetrievalConfig  # noqa: E402

EVAL = ROOT / "eval"
DATASET = EVAL / "dataset.jsonl"
RETRIEVAL_SET = EVAL / "data" / "retrieval_v1.jsonl"
CORRECTIONS = EVAL / "data" / "corrections_v1.jsonl"
FAULT_CASES = EVAL / "fault_cases.json"
LOCK = EVAL / "datasets.lock.json"
BASELINE = EVAL / "baseline.json"


def sha256(path: Path) -> str:
    """Hash of the file's content with line endings normalised, so a CRLF checkout on Windows and
    an LF checkout in CI lock to the same value."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def lock_entry(path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"sha256": sha256(path)}
    if path.suffix == ".jsonl" and path.name != "corrections_v1.jsonl":
        records = load_records(path)
        entry["records"] = len(records)
        entry["labels"] = dict(sorted(Counter(r.expected_verdict.value for r in records).items()))
    return entry


def check_lock(lock: dict[str, Any]) -> list[str]:
    """Files whose content no longer matches the lock: labels changed without updating it."""
    problems = []
    for name, expected in lock["files"].items():
        path = ROOT / name
        if not path.exists():
            problems.append(f"{name}: missing")
        elif sha256(path) != expected["sha256"]:
            problems.append(f"{name}: content changed since it was locked")
    return problems


def ratio_dict(r) -> dict[str, Any]:
    return {"numerator": r.numerator, "denominator": r.denominator, "value": r.value}


def resolve(report: dict[str, Any], path: str) -> Any:
    """The value at a "/"-separated path such as "retrieval/dataset.jsonl/recall_at_5"."""
    value: Any = report
    for part in path.split("/"):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"baseline gate metric {path!r} does not exist in the report")
        value = value[part]
    return value


def apply_gates(report: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    model_run = report["run"]["verdict_source"] != "abstain"
    gates = []
    for gate in baseline["gates"]:
        entry = {k: gate[k] for k in ("name", "metric", "op", "value", "applies_to")}
        if gate["applies_to"] == "model_run" and not model_run:
            entry.update(status="NOT APPLICABLE", measured=None, note="needs --verdicts openrouter or --predictions")
        elif gate["value"] is None:
            entry.update(status="NOT ENFORCED", measured=None, note=gate.get("note", "no baseline"))
        else:
            measured = resolve(report, gate["metric"])
            if isinstance(measured, dict):
                measured = measured["value"]
            if measured is None:
                entry.update(status="NOT ENFORCED", measured=None, note="metric undefined (zero denominator)")
            else:
                ok = measured >= gate["value"] if gate["op"] == ">=" else measured <= gate["value"]
                entry.update(status="PASS" if ok else "FAIL", measured=measured, note=gate.get("note", ""))
        gates.append(entry)
    return gates


def evaluate_all(args: argparse.Namespace) -> dict[str, Any]:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    problems = check_lock(lock)
    if problems:
        raise EvaluationInputError("label lock mismatch: " + "; ".join(problems) +
                                   ". If the change is intended, update eval/datasets.lock.json in the same review.")
    provider = None
    if args.verdicts == "openrouter":
        from inkloom_verify.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider.from_env()
    verdict_source = "predictions" if args.predictions else args.verdicts
    commit = _git(["rev-parse", "HEAD"], ROOT)
    report: dict[str, Any] = {
        "run": {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "engine_version": __version__,
            "python": platform.python_version(),
            "git_commit": commit,
            "git_dirty": bool(_git(["status", "--porcelain", "--", "."], ROOT)) if commit else None,
            "verdict_source": verdict_source,
        },
        "datasets": {name: entry for name, entry in lock["files"].items()},
    }
    records = load_records(DATASET)
    report["datasets"]["human_reviewed"] = sum(1 for r in records if r.reviewed_by)

    # 2. Verdicts
    verdicts = run(
        DATASET,
        baseline="abstain" if verdict_source == "abstain" else None,
        predictions_path=Path(args.predictions) if args.predictions else None,
        engine_provider=provider,
        retrieval=None,
        save_predictions=args.out / "predictions.jsonl" if provider else None,
    )
    v, c = verdicts.results.verdict, verdicts.results.citations
    report["verdicts"] = {
        "source": verdict_source,
        "is_model_quality": verdict_source != "abstain",
        "examples": verdicts.results.counts.examples,
        "accuracy": ratio_dict(v.accuracy),
        "per_class": {cls.value: {"precision": ratio_dict(m.precision), "recall": ratio_dict(m.recall), "f1": m.f1}
                      for cls, m in v.per_class.items()},
        "macro_f1": v.macro_f1.value,
        "confusion": {g.value: {p.value: n for p, n in row.items()} for g, row in v.confusion.items()},
        "abstention_rate": ratio_dict(v.abstention_rate),
        "error_rate": ratio_dict(v.error_rate),
        "false_supported_rate": ratio_dict(v.false_supported_rate),
        "citation_validity": ratio_dict(c.validity),
        "grounding": ratio_dict(c.grounding),
        "fully_correct": ratio_dict(c.fully_correct),
        "by_split": {s.value: ratio_dict(r) for s, r in verdicts.results.by_split.items()},
        "failure_counts": {k.value: n for k, n in verdicts.results.failures.counts.items() if n},
    }

    # 3. Retrieval, separately
    report["retrieval"] = {}
    for path in (DATASET, RETRIEVAL_SET):
        entry = {}
        for k in (1, 3, 5):
            r = run(path, baseline="abstain", retrieval=(ChunkingConfig(), RetrievalConfig(top_k=k))).results.retrieval
            entry[f"recall_at_{k}"] = ratio_dict(r.evidence_hit_rate)
        report["retrieval"][path.name] = entry

    # 4. Corrections, separately
    cases = load_cases(CORRECTIONS)
    checker = check_candidates(cases)
    report["corrections"] = {
        "checker": {
            "candidates": checker.candidates,
            "correctly_accepted": ratio_dict(checker.correctly_accepted),
            "correctly_rejected": ratio_dict(checker.correctly_rejected),
            "false_accepts": len(checker.false_accepts),
            "false_rejects": [f"{o.case_id}: {o.original_text!r} -> {o.replacement_text!r}" for o in checker.false_rejects],
        },
        "live": run_live(cases, provider).model_dump(mode="json", exclude={"outcomes"}) if provider else None,
    }

    # 5. Enforcement (scripted adversaries)
    report["enforcement"] = {
        name: scripted.enforcement(records, name, adversary).model_dump(mode="json")
        for name, adversary in scripted.ADVERSARIES.items()
    }

    # 6. Error handling (fault injection)
    document = next(d for r in records for d in r.references if d.doc_id == "pods-fact-sheet")
    outcomes = [scripted.run_fault_case(case, scripted.fault_request(document)) for case in scripted.load_fault_cases(FAULT_CASES)]
    report["faults"] = {
        "pass_rate": ratio_dict(scripted.fault_pass_rate(outcomes)),
        "failed": [o.model_dump(mode="json") for o in outcomes if not o.passed],
    }
    return report


def pct(r: dict[str, Any]) -> str:
    return "n/a" if r["value"] is None else f"{r['value']:.1%} ({r['numerator']}/{r['denominator']})"


def markdown(report: dict[str, Any]) -> str:
    run_info, v = report["run"], report["verdicts"]
    lines = [
        "# Verification engine evaluation report",
        "",
        f"- Run: {run_info['created_at']} · engine {run_info['engine_version']} · Python {run_info['python']}",
        f"- Commit: {run_info['git_commit'] or 'unknown'}" + (" (uncommitted changes)" if run_info["git_dirty"] else ""),
        f"- Verdict source: **{v['source']}**"
        + ("" if v["is_model_quality"] else " — a floor, **not model accuracy** (no live model was run)"),
        f"- Human-reviewed labels in eval/dataset.jsonl: {report['datasets']['human_reviewed']}/{v['examples']}",
        "",
        "## Verdicts (eval/dataset.jsonl)",
        "",
        f"Examples: {v['examples']} · accuracy {pct(v['accuracy'])} · macro F1 "
        + ("n/a" if v["macro_f1"] is None else f"{v['macro_f1']:.3f}"),
        f"Abstention {pct(v['abstention_rate'])} · error {pct(v['error_rate'])} · false-SUPPORTED {pct(v['false_supported_rate'])}",
        f"Citation validity {pct(v['citation_validity'])} · grounding {pct(v['grounding'])} · fully correct {pct(v['fully_correct'])}",
        "",
        "| Class | Precision | Recall | F1 |",
        "|---|---|---|---|",
    ]
    for cls in GOLD_CLASSES:
        m = v["per_class"][cls.value]
        f1 = "n/a" if m["f1"] is None else f"{m['f1']:.3f}"
        lines.append(f"| {cls.value} | {pct(m['precision'])} | {pct(m['recall'])} | {f1} |")
    lines += ["", "Confusion (rows = label, columns = prediction):", "",
              "| | " + " | ".join(p.value for p in PREDICTED_CLASSES) + " |",
              "|---|" + "---|" * len(PREDICTED_CLASSES)]
    for g in GOLD_CLASSES:
        lines.append(f"| {g.value} | " + " | ".join(str(v["confusion"][g.value][p.value]) for p in PREDICTED_CLASSES) + " |")
    lines += ["", "## Retrieval recall@k (deterministic)", "", "| Dataset | @1 | @3 | @5 |", "|---|---|---|---|"]
    for name, entry in report["retrieval"].items():
        lines.append(f"| {name} | {pct(entry['recall_at_1'])} | {pct(entry['recall_at_3'])} | {pct(entry['recall_at_5'])} |")
    ch = report["corrections"]["checker"]
    lines += ["", "## Corrections", "",
              f"Deterministic checks on {ch['candidates']} labelled edits: bad rejected {pct(ch['correctly_rejected'])}, "
              f"good accepted {pct(ch['correctly_accepted'])}, false accepts {ch['false_accepts']}.",
              f"Live corrector: {'not run' if report['corrections']['live'] is None else report['corrections']['live']}",
              "", "## Enforcement (scripted adversaries; not model quality)", "",
              "| Adversary | Definite | Accepted | Accepted quotes verbatim | Quotes not in any source | False-SUPPORTED |",
              "|---|---|---|---|---|---|"]
    for name, e in report["enforcement"].items():
        lines.append(f"| {name} | {e['definite_answers']} | {e['accepted']} | {e['accepted_citations_verbatim']}/{e['accepted_citations']} | "
                     f"{e['accepted_quotes_not_in_any_source']} | {pct(e['false_supported'])} |")
    f = report["faults"]
    lines += ["", "## Error handling (fault injection)", "", f"Fault cases passed: {pct(f['pass_rate'])}"]
    lines += [f"- FAILED: {o['name']} {o['observed']}" for o in f["failed"]]
    if "gates" in report:
        lines += ["", "## Regression gates (eval/baseline.json)", "", "| Gate | Measured | Required | Status |", "|---|---|---|---|"]
        for g in report["gates"]:
            required = "—" if g["value"] is None else f"{g['op']} {g['value']}"
            measured = "—" if g["measured"] is None else g["measured"]
            lines.append(f"| {g['name']} | {measured} | {required} | {g['status']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python eval/run_eval.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--verdicts", choices=["abstain", "openrouter"], default="abstain")
    source.add_argument("--predictions", help="replay a saved EvalPrediction JSONL for eval/dataset.jsonl")
    parser.add_argument("--out", type=Path, help="report directory (default: reports/<UTC timestamp>)")
    parser.add_argument("--check-baseline", nargs="?", const=str(BASELINE), help="apply regression gates; exit 1 on failure")
    args = parser.parse_args(argv)
    args.out = args.out or ROOT / "reports" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        report = evaluate_all(args)
    except (EvaluationInputError, ProviderError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    failed = False
    if args.check_baseline:
        try:
            report["gates"] = apply_gates(report, json.loads(Path(args.check_baseline).read_text(encoding="utf-8")))
        except (ValueError, OSError, KeyError) as error:
            print(f"error: invalid baseline: {error}", file=sys.stderr)
            return 2
        failed = any(g["status"] == "FAIL" for g in report["gates"])
    (args.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    text = markdown(report)
    (args.out / "report.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"Report written to {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
