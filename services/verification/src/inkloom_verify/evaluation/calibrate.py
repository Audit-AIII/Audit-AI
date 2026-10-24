"""Select the decision-policy thresholds on the development split (EVAL.md Phase 5).

``python -m inkloom_verify.evaluation.calibrate --run-dir RUN [--out proposal.json]``

``RUN`` is a full-pipeline ``run_eval.py`` output directory (``report.json`` and
``cases.jsonl``). Each candidate policy is re-applied, with the same ``review_reasons`` function
the pipeline uses, to the recorded claims of **dev records only**. Held-out records are never
read: the split comes from the locked dataset, not from the run, and ``--split heldout`` is refused.

Selection, in priority order:

1. **Safety (hard constraint):** no record labelled CONTRADICTED or NOT_ENOUGH_EVIDENCE may be
   auto-cleared (cleared without review). Missed contradictions come first, so this is never
   traded against review volume.
2. **Volume:** among the safe candidates, the lowest review share.
3. **Ties:** the stricter candidate.

A safe candidate always exists: ``never`` clears nothing. When every looser candidate would
clear a non-SUPPORTED record, ``never`` (every claim goes to a person) is the proposal, and it
says so.

The proposal is only valid for selection when the run's answers came from a live model
(``verdicts.is_model_quality``); otherwise it is marked as a harness check. Nothing is written
to ``eval/decision_policy.json``: a person reviews the proposal and applies it.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any

from inkloom_verify.decision_policy import DecisionPolicy, review_reasons
from inkloom_verify.evaluation.pipeline_predictor import CaseOutcome
from inkloom_verify.evaluation.runner import load_records
from inkloom_verify.schemas import EvidenceStrength, Verdict

STRICTNESS = {"moderate": 0, "strong": 1, "never": 2}
CANDIDATES = [
    DecisionPolicy(auto_clear_min_strength=s, compound_min_citations=n)
    for s, n in itertools.product(("moderate", "strong", "never"), (1, 2, 3))
]


class CalibrationError(ValueError):
    pass


def routed(outcome: CaseOutcome, policy: DecisionPolicy) -> bool:
    """Whether a record goes to a person under ``policy``: any claim with a reason, or no claim at all."""
    if not outcome.claims:
        return True
    return any(
        review_reasons(
            Verdict(c.verdict),
            EvidenceStrength(c.evidence_strength),
            c.statement or c.text,
            len(c.citations),
            policy,
        )
        for c in outcome.claims
    )


def evaluate_candidate(
    policy: DecisionPolicy, outcomes: list[CaseOutcome], labels: dict[str, str]
) -> dict[str, Any]:
    cleared = [o for o in outcomes if not routed(o, policy)]
    unsafe = [o.record_id for o in cleared if labels[o.record_id] != Verdict.SUPPORTED.value]
    missed_contradictions = [
        o.record_id for o in cleared if labels[o.record_id] == Verdict.CONTRADICTED.value
    ]
    reviewed = len(outcomes) - len(cleared)
    return {
        "policy": policy.model_dump(mode="json"),
        "records": len(outcomes),
        "routed_to_review": reviewed,
        "review_share": reviewed / len(outcomes) if outcomes else None,
        "auto_cleared": len(cleared),
        "auto_cleared_not_supported": unsafe,
        "auto_cleared_contradicted": missed_contradictions,
        "safe": not unsafe,
    }


def calibrate(run_dir: Path, dataset: Path, split: str = "dev") -> dict[str, Any]:
    if split != "dev":
        raise CalibrationError(
            "thresholds are selected on the dev split only; the held-out split is for final evaluation"
        )
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    cases_file = run_dir / "cases.jsonl"
    if not cases_file.exists():
        raise CalibrationError(
            "the run has no cases.jsonl: calibrate from a full-pipeline run (--pipeline full)"
        )
    records = {r.record_id: r for r in load_records(dataset)}
    dev = {rid for rid, r in records.items() if r.split.value == "dev"}
    outcomes = []
    for line in cases_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record_id = json.loads(line)["record_id"]
        if record_id in dev:  # held-out lines are skipped before they are parsed further
            outcomes.append(CaseOutcome.model_validate_json(line))
    if not outcomes:
        raise CalibrationError("the run has no outcomes for dev records")
    labels = {rid: records[rid].expected_verdict.value for rid in dev}
    results = [evaluate_candidate(p, outcomes, labels) for p in CANDIDATES]
    # The "never" candidates clear nothing, so a safe candidate always exists: when every looser
    # candidate would clear a non-SUPPORTED record, the proposal is that every claim goes to a
    # person.
    safe = [r for r in results if r["safe"]]
    chosen = min(
        safe,
        key=lambda r: (
            r["routed_to_review"],
            -STRICTNESS[r["policy"]["auto_clear_min_strength"]],
            -r["policy"]["compound_min_citations"],
        ),
    )
    note = "the safe candidate with the lowest review share" + (
        "; every looser candidate would auto-clear a non-SUPPORTED record, so every claim goes to a person"
        if chosen["policy"]["auto_clear_min_strength"] == "never"
        else ""
    )
    model_quality = bool(report.get("verdicts", {}).get("is_model_quality"))
    return {
        "split": "dev",
        "dev_records_with_outcomes": len(outcomes),
        "heldout_records_read": 0,
        "source_run": {
            "dir": run_dir.name,
            "verdict_source": report["run"].get("verdict_source"),
            "dataset_sha256": report["run"].get("dataset", {}).get("sha256"),
            "model_configuration": report["run"].get("model_configuration"),
        },
        "valid_for_selection": model_quality,
        "validity_note": "answers came from a live model"
        if model_quality
        else "NOT VALID FOR SELECTION: these answers did not come from a live model; this only checks the harness",
        "proposal": chosen["policy"],
        "selection_rule": note,
        "candidates": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m inkloom_verify.evaluation.calibrate", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "eval" / "dataset.jsonl",
    )
    parser.add_argument("--split", default="dev")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = calibrate(args.run_dir, args.dataset, args.split)
    except (CalibrationError, OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
