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

**The verdict section runs the real pipeline** (``--pipeline full``, the default):
``inkloom_verify.pipeline.verify_request`` once per record, the function ``POST /v1/verify``
uses, so extraction, retrieval, verification, the citation guard, correction and the human-review
decision all run as in production (``evaluation/pipeline_predictor.py``). ``--pipeline verifier``
runs only retrieval, the verifier and the guard on the labelled claim, as before. Every record's
outcome is written to ``cases.jsonl`` next to the report.

Providers: ``--verdicts openrouter`` calls the live model (``--record FILE`` also saves every
reply to a cassette); ``--replay FILE`` answers from a saved cassette, offline and
deterministically, and reports any request it has no recording for as a provider error, never a
made-up reply. The dataset is validated before anything runs.

Exit codes: 0 ran and every gate passed; 1 a gate failed; 2 an input or configuration problem
(invalid dataset, changed label lock, missing credentials, unreadable cassette); 3 the evaluation
ran but no record received a verdict (for example the provider failed on every call).

``--prompts v1|v2`` pins the prompt version of every live stage (default: the components' active
defaults); the versions are recorded in the report, with the model configuration (never the key)
and per-stage call statistics. ``--dry-run`` replaces the provider with an offline stub that
answers every call minimally, to count calls and input size before paying for a live run.

Only sections 2 and 4 with a live source say anything about model quality. Sections 3, 5 and 6
are deterministic and need no credentials; CI runs them on every change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
from inkloom_verify.correction import CorrectionConfig  # noqa: E402
from inkloom_verify.evaluation.dataset import validate_dataset  # noqa: E402
from inkloom_verify.evaluation.extraction import evaluate_extraction, load_extraction_records  # noqa: E402
from inkloom_verify.evaluation.pipeline_predictor import (
    PipelinePredictor,
    decision_policy,
    retrieval_parameters,
)  # noqa: E402
from inkloom_verify.evaluation.replay import CassetteError, RecordingProvider, ReplayProvider  # noqa: E402
from inkloom_verify.evaluation import report as reporting  # noqa: E402
from inkloom_verify.evaluation import required_metrics  # noqa: E402
from inkloom_verify.evaluation.pipeline_predictor import CaseOutcome  # noqa: E402
from inkloom_verify.evaluation.summary import build_summary, incomplete_summary  # noqa: E402
from inkloom_verify.evaluation.oracle import OracleProvider, OraclePredictor  # noqa: E402
from inkloom_verify.decision_policy import DecisionPolicy  # noqa: E402
from inkloom_verify.extraction import ExtractionConfig  # noqa: E402
from inkloom_verify.pipeline import PipelineConfig  # noqa: E402
from inkloom_verify.verification import VerificationConfig  # noqa: E402
from inkloom_verify.evaluation.corrections import check_candidates, load_cases, run_live  # noqa: E402
from inkloom_verify.evaluation.metrics import GOLD_CLASSES, PREDICTED_CLASSES  # noqa: E402
from inkloom_verify.evaluation.runner import (  # noqa: E402
    AbstainBaseline,
    EvaluationInputError,
    _git,
    load_predictions,
    load_records,
    run,
)
from inkloom_verify.providers.base import JsonCompletion, JsonCompletionRequest, ProviderError  # noqa: E402
from inkloom_verify.prompts import correction as correction_prompt  # noqa: E402
from inkloom_verify.prompts import extraction as extraction_prompt  # noqa: E402
from inkloom_verify.prompts import verification as verification_prompt  # noqa: E402
from inkloom_verify.retrieval import RetrievalConfig  # noqa: E402

EVAL = ROOT / "eval"
DATASET = EVAL / "dataset.jsonl"
RETRIEVAL_SET = EVAL / "data" / "retrieval_v1.jsonl"
CORRECTIONS = EVAL / "data" / "corrections_v1.jsonl"
EXTRACTION = EVAL / "data" / "extraction_v1.jsonl"
FAULT_CASES = EVAL / "fault_cases.json"
LOCK = EVAL / "datasets.lock.json"
BASELINE = EVAL / "baseline.json"
POLICY = EVAL / "decision_policy.json"


# Prompt sets the evaluation can pin. Each is a released version per stage (prompts.lock.json).
PROMPT_SETS = {
    "v1": {
        "extract_claims": "extract-claims-v1",
        "verify_claim": "verify-claim-v1",
        "correct_claim": "correct-claim-v1",
    },
    "v2": {
        "extract_claims": "extract-claims-v2",
        "verify_claim": "verify-claim-v2",
        "correct_claim": "correct-claim-v2",
    },
}
REPAIR_MARKER = (
    "Your previous reply could not be used:"  # the start of every repair message (prompts/*.py)
)


def active_prompts() -> dict[str, str]:
    return {
        "extract_claims": extraction_prompt.PROMPT_VERSION,
        "verify_claim": verification_prompt.PROMPT_VERSION,
        "correct_claim": correction_prompt.PROMPT_VERSION,
    }


class CountingProvider:
    """Wraps the provider to count, per stage: calls, repair calls (the previous reply did not
    match the schema), provider errors by code, and characters sent. Counts only; it never stores
    or logs content."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.name = inner.name
        self.stats: dict[str, dict[str, Any]] = {}

    def sampling(self) -> dict[str, Any]:
        return self.inner.sampling()

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        s = self.stats.setdefault(
            request.schema_name, {"calls": 0, "repair_calls": 0, "input_chars": 0, "errors": {}}
        )
        s["calls"] += 1
        s["repair_calls"] += REPAIR_MARKER in request.user
        s["input_chars"] += len(request.system) + len(request.user)
        try:
            return self.inner.complete_json(request)
        except ProviderError as error:
            s["errors"][error.code.value] = s["errors"].get(error.code.value, 0) + 1
            raise


class DryRunProvider:
    """Offline stand-in for --dry-run: answers every call with the smallest valid reply (each
    sentence one factual claim quoting itself, NOT_ENOUGH_EVIDENCE, decline), so it counts the
    calls a live run makes at least once. Live runs make more: repairs, claims split further, and
    re-checks after proposed corrections."""

    name = "dry-run"

    def sampling(self) -> dict[str, Any]:
        return {}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        if request.schema_name == "claim_extraction":
            sentences = json.loads(
                request.user.split("<content_json>\n", 1)[1].rsplit("\n</content_json>", 1)[0]
            )["sentences"]
            data: dict[str, Any] = {
                "statements": [
                    {
                        "sentence_id": s["id"],
                        "kind": "factual",
                        "claims": [{"text": s["text"], "source_quote": s["text"]}],
                    }
                    for s in sentences
                ]
            }
        elif request.schema_name == "claim_verification":
            data = {"verdict": "NOT_ENOUGH_EVIDENCE", "citations": [], "rationale": "dry run"}
        else:
            data = {
                "status": "needs_human_review",
                "original_text": "",
                "replacement_text": "",
                "citations": [],
                "reason": "dry run",
            }
        return JsonCompletion(data=data, model="dry-run", attempts=1)


def model_configuration(provider) -> dict[str, Any] | None:
    """What a live run used: models in order, sampling and limits. Never the key."""
    settings = getattr(provider, "settings", None)
    if settings is None:
        return {"provider": provider.name}
    return {
        "provider": provider.name,
        "models": list(settings.models),
        "base_url": settings.base_url,
        "temperature": settings.temperature,
        "seed": settings.seed,
        "structured_output": settings.structured_output,
        "data_collection": settings.data_collection,
        "timeout_seconds": settings.timeout_seconds,
        "max_retries": settings.max_retries,
    }


def sha256(path: Path) -> str:
    """Hash of the file's content with line endings normalised, so a CRLF checkout on Windows and
    an LF checkout in CI lock to the same value."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def lock_entry(path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"sha256": sha256(path)}
    if path.name == EXTRACTION.name:
        extraction_records = load_extraction_records(path)
        entry["records"] = len(extraction_records)
        entry["claims"] = sum(len(r.claims) for r in extraction_records)
    elif path.suffix == ".jsonl" and path.name != "corrections_v1.jsonl":
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
    # "always": every run. "model_run": answers from a live model (or its saved predictions or
    # recording). "oracle": the scripted gold-answer run CI uses to measure the engine's ceiling.
    kinds = {
        "always": True,
        "model_run": bool(report["verdicts"]["is_model_quality"]),
        "oracle": report["run"]["verdict_source"] == "oracle",
    }
    gates = []
    for gate in baseline["gates"]:
        entry = {k: gate[k] for k in ("name", "metric", "op", "value", "applies_to")}
        if gate["applies_to"] not in kinds:
            raise KeyError(f"unknown applies_to {gate['applies_to']!r}")
        if not report["run"]["dataset"]["locked"]:
            # Baselines were measured on the locked eval/dataset.jsonl; they mean nothing elsewhere.
            entry.update(
                status="NOT APPLICABLE",
                measured=None,
                note="baselines apply to the locked eval/dataset.jsonl only",
            )
        elif not kinds[gate["applies_to"]]:
            needs = (
                "a live model run (--verdicts openrouter, --predictions, or a live --replay)"
                if gate["applies_to"] == "model_run"
                else "--verdicts oracle"
            )
            entry.update(status="NOT APPLICABLE", measured=None, note=f"needs {needs}")
        elif gate["value"] is None:
            entry.update(status="NOT ENFORCED", measured=None, note=gate.get("note", "no baseline"))
        else:
            measured = resolve(report, gate["metric"])
            if isinstance(measured, dict):
                measured = measured["value"]
            if measured is None:
                entry.update(
                    status="NOT ENFORCED", measured=None, note="metric undefined (zero denominator)"
                )
            else:
                ok = measured >= gate["value"] if gate["op"] == ">=" else measured <= gate["value"]
                entry.update(
                    status="PASS" if ok else "FAIL", measured=measured, note=gate.get("note", "")
                )
        gates.append(entry)
    return gates


def evaluate_all(args: argparse.Namespace) -> dict[str, Any]:
    dataset = Path(args.dataset).resolve() if args.dataset else DATASET
    validation = validate_dataset(
        dataset, check_mix=dataset == DATASET
    )  # the mix is a property of the canonical set
    if not validation.ok:
        raise EvaluationInputError(
            f"invalid dataset {dataset.name}: " + "; ".join(validation.problems[:10])
        )
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    problems = check_lock(lock)
    if problems:
        raise EvaluationInputError(
            "label lock mismatch: "
            + "; ".join(problems)
            + ". If the change is intended, update eval/datasets.lock.json in the same review."
        )
    provider = None
    oracle: OracleProvider | None = None
    replay: ReplayProvider | None = None
    prompts = PROMPT_SETS[args.prompts] if args.prompts else active_prompts()
    if args.replay:
        try:
            provider = replay = ReplayProvider(Path(args.replay))
        except CassetteError as error:
            raise EvaluationInputError(str(error)) from None
    elif args.verdicts == "oracle":
        oracle = OracleProvider()
        provider = oracle
    elif args.verdicts == "openrouter":
        if args.dry_run:
            provider = DryRunProvider()
        else:
            from inkloom_verify.providers.openrouter import OpenRouterProvider

            provider = OpenRouterProvider.from_env()
    configuration = (
        (replay.header.get("model_configuration") or {"provider": replay.name})
        if replay
        else (model_configuration(provider) if provider else None)
    )
    if args.record and provider is not None and replay is None and not args.dry_run:
        provider = RecordingProvider(
            provider,
            Path(args.record),
            {"model_configuration": configuration, "prompt_versions": prompts},
        )
    counting = CountingProvider(provider) if provider else None
    provider = counting or provider
    verdict_source = (
        "predictions"
        if args.predictions
        else "replay"
        if replay
        else "dry-run"
        if args.dry_run
        else args.verdicts
    )
    policy_file = Path(args.policy) if args.policy else POLICY
    try:
        policy_doc = json.loads(policy_file.read_text(encoding="utf-8"))
        policy = DecisionPolicy.model_validate(policy_doc["policy"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise EvaluationInputError(
            f"invalid decision policy {policy_file.name}: {type(error).__name__}"
        ) from None
    pipeline_config = PipelineConfig(
        decision_policy=policy,
        extraction=ExtractionConfig(prompt_version=prompts["extract_claims"]),
        verification=VerificationConfig(prompt_version=prompts["verify_claim"]),
        correction=CorrectionConfig(prompt_version=prompts["correct_claim"]),
    )
    pipeline_mode = args.pipeline if provider else None
    if oracle is not None:
        predictor = OraclePredictor(oracle, provider, pipeline_config)
    else:
        predictor = (
            PipelinePredictor(provider, pipeline_config)
            if provider and args.pipeline == "full"
            else None
        )
    live = (
        provider if oracle is None else None
    )  # the oracle answers verdicts only; never shown as a live model
    commit = _git(["rev-parse", "HEAD"], ROOT)
    report: dict[str, Any] = {
        "run": {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "engine_version": __version__,
            "python": platform.python_version(),
            "git_commit": commit,
            "git_dirty": bool(_git(["status", "--porcelain", "--", "."], ROOT)) if commit else None,
            "verdict_source": verdict_source,
            "pipeline": pipeline_mode,
            "dataset": {
                "path": dataset.relative_to(ROOT).as_posix()
                if dataset.is_relative_to(ROOT)
                else dataset.as_posix(),
                "sha256": sha256(dataset),
                "records": validation.records,
                "locked": dataset == DATASET,
                "labels": validation.labels,
                "groups": validation.groups,
            },
            "retrieval_parameters": retrieval_parameters(pipeline_config),
            "decision_policy": decision_policy(pipeline_config)
            | {"file": policy_file.name, "calibration": policy_doc.get("calibration")},
            "replay": {
                "cassette": Path(args.replay).name,
                "sha256": replay.sha256,
                "source": replay.header.get("source"),
                "recorded_at": replay.header.get("created_at"),
                "recorded_calls": replay.recorded_calls,
            }
            if replay
            else None,
            "prompt_set": args.prompts or "active defaults",
            # The versions the live stages were configured with; the verifier's versions actually
            # sent are also in verdicts.prompt_versions_sent.
            "prompt_versions": prompts if provider else None,
            "model_configuration": configuration,
        },
        "datasets": {name: entry for name, entry in lock["files"].items()},
    }
    records = load_records(dataset)
    report["datasets"]["human_reviewed"] = sum(1 for r in records if r.reviewed_by)

    # 2. Verdicts
    verdicts = run(
        dataset,
        baseline="abstain" if verdict_source == "abstain" else None,
        predictions_path=Path(args.predictions) if args.predictions else None,
        engine_provider=provider,
        retrieval=None,
        save_predictions=args.out / "predictions.jsonl" if provider else None,
        verifier_prompt=prompts["verify_claim"] if provider else None,
        engine_predictor=predictor,
    )
    report["cases"] = None
    report["failed_cases"] = None
    if predictor is not None:
        report["failed_cases"] = [
            {
                "record_id": o.record_id,
                "expected": o.expected,
                "predicted": o.predicted,
                "outcome": o.outcome,
                "reason": o.reason,
            }
            for o in predictor.outcomes.values()
            if o.outcome != "correct"
        ]
        outcomes = list(predictor.outcomes.values())
        (args.out / "cases.jsonl").write_text(
            "".join(o.model_dump_json() + chr(10) for o in outcomes), encoding="utf-8"
        )
        report["cases"] = {
            "file": "cases.jsonl",
            "records": len(outcomes),
            "outcomes": dict(sorted(Counter(o.outcome for o in outcomes).items())),
            "reasons": dict(sorted(Counter(o.reason for o in outcomes if o.reason).items())),
            "requires_human_review": sum(1 for o in outcomes if o.requires_human_review),
            "claims": sum(len(o.claims) for o in outcomes),
            "corrections": dict(
                sorted(
                    Counter(
                        c.correction.status for o in outcomes for c in o.claims if c.correction
                    ).items()
                )
            ),
            "replay_misses": replay.misses if replay else None,
        }
    v, c = verdicts.results.verdict, verdicts.results.citations
    report["verdicts"] = {
        "source": verdict_source,
        # Only answers from a live model say anything about model quality: a live run, a saved
        # live run's predictions, or a replayed cassette that was recorded from a live provider.
        # Decided by the provider that actually answered (for a replay: the one it was recorded
        # from), never by the command-line flag alone.
        "is_model_quality": verdict_source == "predictions"
        or (
            verdict_source in ("openrouter", "replay")
            and bool(configuration)
            and configuration.get("provider") == "openrouter"
        ),
        "prompt_versions_sent": verdicts.manifest.predictor.prompt_versions,
        "model_ids": verdicts.manifest.predictor.model_ids,
        "examples": verdicts.results.counts.examples,
        "accuracy": ratio_dict(v.accuracy),
        "per_class": {
            cls.value: {
                "precision": ratio_dict(m.precision),
                "recall": ratio_dict(m.recall),
                "f1": m.f1,
            }
            for cls, m in v.per_class.items()
        },
        "macro_f1": v.macro_f1.value,
        "confusion": {
            g.value: {p.value: n for p, n in row.items()} for g, row in v.confusion.items()
        },
        "abstention_rate": ratio_dict(v.abstention_rate),
        "error_rate": ratio_dict(v.error_rate),
        "false_supported_rate": ratio_dict(v.false_supported_rate),
        "citation_validity": ratio_dict(c.validity),
        "grounding": ratio_dict(c.grounding),
        "fully_correct": ratio_dict(c.fully_correct),
        "by_split": {s.value: ratio_dict(r) for s, r in verdicts.results.by_split.items()},
        "by_category": {c.value: ratio_dict(r) for c, r in verdicts.results.by_category.items()},
        "failure_counts": {k.value: n for k, n in verdicts.results.failures.counts.items() if n},
    }

    # 2b. The eight required metrics (EVAL.md Phase 4), from this run's actual predictions and,
    # for a full-pipeline run, its per-case outcomes. Nothing measured elsewhere is substituted.
    if provider:
        predictions = load_predictions(args.out / "predictions.jsonl")
    elif args.predictions:
        predictions = load_predictions(Path(args.predictions))
    else:
        predictions = {r.record_id: AbstainBaseline().predict(r) for r in records}
    report["required_metrics"] = required_metrics.compute(
        records,
        predictions,
        predictor.outcomes if predictor else None,
        pipeline_config.chunking,
        pipeline_config.retrieval,
    ).model_dump(mode="json")
    # The same metrics per split, from the same predictions and outcomes (nothing re-run). The
    # held-out split is never used for calibration (calibrate.py), so its numbers are the ones to
    # quote; the pooled figures above mix it with the dev records thresholds were chosen on.
    report["required_metrics_by_split"] = {}
    for split in sorted({r.split.value for r in records}):
        subset = [r for r in records if r.split.value == split]
        ids = {r.record_id for r in subset}
        outcomes = {k: o for k, o in predictor.outcomes.items() if k in ids} if predictor else None
        report["required_metrics_by_split"][split] = required_metrics.compute(
            subset,
            {k: p for k, p in predictions.items() if k in ids},
            outcomes,
            pipeline_config.chunking,
            pipeline_config.retrieval,
        ).model_dump(mode="json")

    # 3. Retrieval, separately
    report["retrieval"] = {}
    for path in (dataset, RETRIEVAL_SET):
        entry = {}
        for k in (1, 3, 5):
            r = run(
                path, baseline="abstain", retrieval=(ChunkingConfig(), RetrievalConfig(top_k=k))
            ).results.retrieval
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
            "false_rejects": [
                f"{o.case_id}: {o.original_text!r} -> {o.replacement_text!r}"
                for o in checker.false_rejects
            ],
        },
        "live": run_live(cases, live, prompts["correct_claim"], prompts["verify_claim"]).model_dump(
            mode="json", exclude={"outcomes"}
        )
        if live
        else None,
    }

    # 4b. Claim extraction (eval/data/extraction_v1.jsonl): oracle replay, adversaries, live model
    report["extraction"] = evaluate_extraction(
        load_extraction_records(EXTRACTION),
        live=live,
        prompt_version=prompts["extract_claims"] if live else None,
    )
    report["calls"] = counting.stats if counting else None

    # 5. Enforcement (scripted adversaries)
    report["enforcement"] = {
        name: scripted.enforcement(records, name, adversary).model_dump(mode="json")
        for name, adversary in scripted.ADVERSARIES.items()
    }

    # 5b. The same adversaries through the full pipeline and the decision policy (Phase 6):
    # what the code lets past a person when the model is hostile. Deterministic; CI gates on it.
    report["pipeline_safety"] = {
        name: scripted.pipeline_safety(records, adversary)
        for name, adversary in scripted.ADVERSARIES.items()
    }

    # 6. Error handling (fault injection)
    document = next(d for r in records for d in r.references if d.doc_id == "pods-fact-sheet")
    outcomes = [
        scripted.run_fault_case(case, scripted.fault_request(document))
        for case in scripted.load_fault_cases(FAULT_CASES)
    ]
    report["faults"] = {
        "pass_rate": ratio_dict(scripted.fault_pass_rate(outcomes)),
        "failed": [o.model_dump(mode="json") for o in outcomes if not o.passed],
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python eval/run_eval.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--verdicts",
        choices=["abstain", "oracle", "openrouter"],
        default="abstain",
        help="abstain: a floor; oracle: scripted gold answers through the full pipeline (the engine's "
        "ceiling, what CI gates on; not model quality); openrouter: the live model",
    )
    source.add_argument(
        "--predictions", help="replay a saved EvalPrediction JSONL for eval/dataset.jsonl"
    )
    source.add_argument(
        "--replay", help="answer every model call from a cassette recorded with --record (offline)"
    )
    parser.add_argument(
        "--record", help="with --verdicts openrouter: save every model reply to this cassette"
    )
    parser.add_argument(
        "--pipeline",
        choices=["full", "verifier"],
        default="full",
        help="full: verify_request per record (default); verifier: retrieval + verifier + guard only",
    )
    parser.add_argument(
        "--dataset",
        help="evaluate this dataset instead of eval/dataset.jsonl (validated; not locked)",
    )
    parser.add_argument("--policy", help="decision policy file (default eval/decision_policy.json)")
    parser.add_argument(
        "--out",
        type=Path,
        help="artifact directory: report.json, report.md, cases.jsonl, predictions "
        "(default: reports/<UTC timestamp>)",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        help="where the timestamped report is written (default: eval/reports)",
    )
    parser.add_argument(
        "--check-baseline",
        nargs="?",
        const=str(BASELINE),
        help="apply regression gates; exit 1 on failure",
    )
    parser.add_argument(
        "--prompts", choices=sorted(PROMPT_SETS), help="pin every live stage to this prompt set"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with --verdicts openrouter: offline stub, counts calls only",
    )
    args = parser.parse_args(argv)
    if args.dry_run and args.verdicts != "openrouter":
        parser.error("--dry-run needs --verdicts openrouter")
    if args.verdicts == "oracle" and args.pipeline != "full":
        parser.error("--verdicts oracle needs --pipeline full")
    if args.record and args.verdicts != "openrouter":
        parser.error("--record needs --verdicts openrouter")
    args.out = args.out or ROOT / "reports" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.out.mkdir(parents=True, exist_ok=True)
    reports_dir = args.reports_dir or Path(
        os.environ.get("INKLOOM_EVAL_REPORTS_DIR") or EVAL / "reports"
    )
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source = (
        "predictions"
        if args.predictions
        else "replay"
        if args.replay
        else "dry-run"
        if args.dry_run
        else args.verdicts
    )
    try:
        report = evaluate_all(args)
        # Gates are always compared (the report shows the baseline comparison); --check-baseline
        # makes a failed gate fail the command (exit 1), as CI needs.
        report["gates"] = apply_gates(
            report, json.loads(Path(args.check_baseline or BASELINE).read_text(encoding="utf-8"))
        )
    except (EvaluationInputError, ProviderError, ValueError, OSError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        _write_incomplete(reports_dir, started, source, f"{type(error).__name__}: {error}")
        return 2
    report["run"]["gates_enforced"] = bool(args.check_baseline)
    failed = bool(args.check_baseline) and any(g["status"] == "FAIL" for g in report["gates"])
    # A run in which no record received a verdict is a failed evaluation, not a result to score.
    cases = report.get("cases")
    no_verdicts = (
        bool(cases)
        and report["run"]["verdict_source"] != "dry-run"
        and cases["records"] > 0
        and set(cases["outcomes"]) <= {"error", "skipped"}
    )
    report["run"]["evaluation_failed"] = no_verdicts
    text = reporting.render_markdown(report)
    (args.out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.out / "report.md").write_text(text, encoding="utf-8")
    paths = reporting.write_report(
        report,
        reports_dir,
        args.out / "cases.jsonl",
        _summary(report, args.out).model_dump(mode="json"),
    )
    print(text)
    print(f"Report written to {paths['markdown']} (artifacts in {args.out})")
    if no_verdicts:
        print("error: the evaluation ran but no record received a verdict", file=sys.stderr)
        return 3
    return 1 if failed else 0


def _summary(report: dict[str, Any], out: Path):
    """The Trust Scorecard summary of this run, from its own report, cases and dataset."""
    dataset = (
        ROOT / report["run"]["dataset"]["path"]
        if not Path(report["run"]["dataset"]["path"]).is_absolute()
        else Path(report["run"]["dataset"]["path"])
    )
    records = {r.record_id: r for r in load_records(dataset)}
    cases_file = out / "cases.jsonl"
    cases = (
        {
            o.record_id: o
            for o in (
                CaseOutcome.model_validate_json(line)
                for line in cases_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        }
        if report.get("cases") and cases_file.exists()
        else None
    )
    return build_summary(report, cases, records)


def _write_incomplete(reports_dir: Path, started: str, source: str | None, error: str) -> None:
    """A run that stopped still leaves a report: incomplete, with the error and nothing invented."""
    commit = _git(["rev-parse", "HEAD"], ROOT)
    report = {
        "run": {
            "created_at": started,
            "incomplete": True,
            "error": error[:500],
            "verdict_source": source,
            "engine_version": __version__,
            "python": platform.python_version(),
            "git_commit": commit,
        }
    }
    try:
        paths = reporting.write_report(
            report, reports_dir, None, incomplete_summary(report).model_dump(mode="json")
        )
        print(f"Incomplete report written to {paths['markdown']}", file=sys.stderr)
    except OSError as write_error:
        print(
            f"error: could not write the incomplete report: {write_error.strerror}", file=sys.stderr
        )


if __name__ == "__main__":
    sys.exit(main())
