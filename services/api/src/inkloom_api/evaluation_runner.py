"""Trust Scorecard: runs the engine's labelled claim-verification evaluation through this
backend's provider chain and turns the result into the numbers the Scorecard page shows.

Built from Member 2's own evaluation pieces, read-only (services/verification/eval/run_eval.py
uses the same ones): `load_records` on `eval/dataset.jsonl`, the label lock in
`eval/datasets.lock.json` (a changed dataset is refused, like run_eval.py does),
`EngineVerifierPredictor` (BM25 retrieval + the real verifier + citation guard), `evaluate()` and
its Trust Scorecard metrics. Definitions are the engine's (inkloom_verify/evaluation/metrics.py):

* flagged = CONTRADICTED or NOT_ENOUGH_EVIDENCE (what the product shows as a problem);
* catch_rate = flagged / claims labelled CONTRADICTED or NOT_ENOUGH_EVIDENCE (recall on claims
  that should be flagged);
* false_positive_rate = flagged / claims labelled SUPPORTED;
* ERROR (provider failure, or the run's call budget ran out) counts as neither flagged nor
  cleared - it lowers the catch rate rather than being hidden, and is reported separately as
  provider_failure_rate.

Every number has a real denominator; a rate whose denominator is zero is null, never 0 or 1.
Model-reported confidence is never used (the verifier's schema doesn't even have one).

What the numbers cover is stated with them (`coverage`): this is run_eval.py's `--pipeline
verifier` mode - retrieval, the verifier and the citation guard on each labelled claim - not the
full review pipeline (extraction, correction, this backend's citation re-validation). The same
metrics are also given per dataset split (`by_split`, dev and held-out, each with its own
denominators), and the run says whether a live model or the offline scripted provider answered
(`provider_mode`, from the model ids that actually answered).
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import inkloom_verify
from inkloom_verify.evaluation import metrics
from inkloom_verify.evaluation.runner import (
    EngineVerifierPredictor,
    EvalPrediction,
    evaluate,
    load_records,
)
from inkloom_verify.prompts import verification as verification_prompt
from inkloom_verify.providers.base import LLMProvider
from inkloom_verify.providers.budget import BudgetedProvider, CallBudget
from inkloom_verify.schemas import EvalRecord, Verdict

from .config import Settings

DATASET_RELATIVE = "eval/dataset.jsonl"
# EngineVerifierPredictor is the only predictor this runner has ever used, so every stored run -
# including ones from before this field existed - is verifier-only.
COVERAGE_VERIFIER_ONLY = "verifier_only"
SCRIPTED_MODEL_PREFIX = "scripted/"  # engine/scripted_provider.py: every scripted model id has it


class EvaluationUnavailableError(Exception):
    """The evaluation cannot run (no provider configured, or the labelled dataset is missing or
    changed since it was locked). The message is safe to show; nothing is stored."""


@dataclass(frozen=True)
class EvaluationResult:
    status: str  # EvaluationRunStatus value
    ran_at: datetime
    sample_size: int
    dataset_version: str
    engine_prompt_version: str | None
    metrics: dict
    limits_note: str


def _engine_root() -> Path:
    # inkloom_verify is installed editable from services/verification/src/inkloom_verify.
    return Path(inkloom_verify.__file__).resolve().parents[2]


def _normalised_sha256(path: Path) -> str:
    """Same hash as run_eval.py's lock check: line endings normalised to LF."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def locate_dataset(settings: Settings) -> tuple[list[EvalRecord], str]:
    """The labelled records and a dataset version string; refuses a dataset that no longer
    matches the engine's label lock (labels must not change silently)."""
    root = _engine_root()
    path = (
        Path(settings.eval_dataset_path) if settings.eval_dataset_path else root / DATASET_RELATIVE
    )
    lock_path = root / "eval" / "datasets.lock.json"
    if not path.is_file() or not lock_path.is_file():
        raise EvaluationUnavailableError(
            "the labelled evaluation dataset is not available on this server"
        )
    digest = _normalised_sha256(path)
    locked = (
        json.loads(lock_path.read_text(encoding="utf-8"))["files"]
        .get(DATASET_RELATIVE, {})
        .get("sha256")
    )
    if not settings.eval_dataset_path and digest != locked:
        raise EvaluationUnavailableError(
            "the labelled evaluation dataset changed since it was locked; refusing to run"
        )
    return load_records(path), f"{path.name}@{digest[:12]}"


def _rate(ratio) -> float | None:
    return round(ratio.value, 4) if ratio.value is not None else None


def _ratio_dict(ratio) -> dict:
    return {"numerator": ratio.numerator, "denominator": ratio.denominator, "value": _rate(ratio)}


def _per_check(records: list[EvalRecord], predictions: dict[str, EvalPrediction]) -> list[dict]:
    """ "verification" over every claim, then one entry per kind of hard case the dataset labels
    (numeric, date, prompt_injection, ...), largest first. Same metric definitions throughout."""

    def entry(name: str, subset: list[EvalRecord]) -> dict:
        confusion = metrics.confusion_matrix(
            (
                r.expected_verdict,
                predictions[r.record_id].verdict if r.record_id in predictions else Verdict.ERROR,
            )
            for r in subset
        )
        return {
            "check": name,
            "catch_rate": _rate(metrics.catch_rate(confusion)),
            "false_positive_rate": _rate(metrics.false_positive_rate(confusion)),
            "n": len(subset),
        }

    by_category: dict[str, list[EvalRecord]] = {}
    for record in records:
        for category in record.categories:
            by_category.setdefault(category.value, []).append(record)
    ordered = sorted(by_category.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [entry("verification", records)] + [entry(name, subset) for name, subset in ordered]


def _by_split(records: list[EvalRecord], predictions: dict[str, EvalPrediction]) -> dict[str, dict]:
    """The headline metrics per dataset split (dev, heldout), each with its own numerators and
    denominators. Held-out records are never used to choose the engine's thresholds (EVAL.md,
    calibrate.py refuses them), so they are the figure to quote; dev and pooled numbers include
    records the engine was tuned on."""
    by_split: dict[str, list[EvalRecord]] = {}
    for record in records:
        by_split.setdefault(record.split.value, []).append(record)
    result = {}
    for split, subset in sorted(by_split.items()):
        confusion = metrics.confusion_matrix(
            (
                r.expected_verdict,
                predictions[r.record_id].verdict if r.record_id in predictions else Verdict.ERROR,
            )
            for r in subset
        )
        result[split] = {
            "n": len(subset),
            "catch_rate": _ratio_dict(metrics.catch_rate(confusion)),
            "false_positive_rate": _ratio_dict(metrics.false_positive_rate(confusion)),
        }
    return result


def provider_mode(model_ids: list[str]) -> str | None:
    """ "live" if only real models answered, "scripted" if only the offline scripted provider did,
    "mixed" if both, None if no model answered at all."""
    scripted = {m.startswith(SCRIPTED_MODEL_PREFIX) for m in model_ids}
    if not scripted:
        return None
    if scripted == {True}:
        return "scripted"
    return "live" if scripted == {False} else "mixed"


def _limits_note(records: list[EvalRecord], errors: int) -> str:
    labels = {
        v: sum(r.expected_verdict is v for r in records)
        for v in (Verdict.SUPPORTED, Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE)
    }
    note = (
        f"Measured on {len(records)} labelled claims from the engine's own test set "
        f"({labels[Verdict.SUPPORTED]} supported, {labels[Verdict.CONTRADICTED]} contradicted, "
        f"{labels[Verdict.NOT_ENOUGH_EVIDENCE]} without evidence), against short synthetic brand documents. "
        "This is a small test set: it shows the checker was tested, not a universal accuracy figure, "
        "and results on your own documents can differ. Per-check numbers rest on even fewer claims."
    )
    if errors:
        note += (
            f" {errors} claim(s) got no verdict (a provider failure or the run's call budget); they count as "
            "not flagged, which lowers the catch rate."
        )
    return note


def run_evaluation(
    provider: LLMProvider, settings: Settings, clock: Callable[[], float] = time.monotonic
) -> EvaluationResult:
    """Runs synchronously, bounded by the engine's call budget (`CallBudget`). Once the budget is
    spent, every remaining claim becomes an ERROR result (the budget's refusal is a
    non-retryable provider error) - the run still finishes and says so."""
    records, dataset_version = locate_dataset(settings)
    budgeted = BudgetedProvider(
        provider,
        CallBudget(
            max_calls=settings.eval_max_calls, deadline_seconds=settings.eval_deadline_seconds
        ),
        clock=clock,
    )
    predictor = EngineVerifierPredictor(budgeted)
    predictions: dict[str, EvalPrediction] = {}
    latencies_ms: list[float] = []
    for record in records:
        started = clock()
        try:
            prediction = predictor.predict(record)
        except Exception:  # noqa: BLE001 - an unexpected failure is this one claim's ERROR, never a crash
            prediction = EvalPrediction(record_id=record.record_id, verdict=Verdict.ERROR)
        latencies_ms.append((clock() - started) * 1000)
        predictions[record.record_id] = prediction

    results = evaluate(records, predictions)
    errors = sum(p.verdict is Verdict.ERROR for p in predictions.values())
    prompt_versions = sorted({p.prompt_version for p in predictions.values() if p.prompt_version})
    scorecard = results.scorecard_candidates
    computed = {
        "catch_rate": _ratio_dict(scorecard.catch_rate),
        "false_positive_rate": _ratio_dict(scorecard.false_positive_rate),
        "per_check": _per_check(records, predictions),
        "by_split": _by_split(records, predictions),
        "coverage": COVERAGE_VERIFIER_ONLY,
        "latency_ms_p50": round(statistics.median(latencies_ms), 1) if latencies_ms else None,
        "provider_failure_rate": round(errors / len(records), 4) if records else None,
        "verdict_accuracy": _rate(results.verdict.accuracy),
        "model_ids": sorted(
            {m for p in predictions.values() if p.model_id for m in p.model_id.split(",")}
        ),
        "calls_used": budgeted.calls,
        "definitions": scorecard.definitions,
    }
    return EvaluationResult(
        status="partial" if errors else "completed",
        ran_at=datetime.now(timezone.utc),
        sample_size=len(records),
        dataset_version=dataset_version,
        engine_prompt_version=prompt_versions[0]
        if prompt_versions
        else verification_prompt.PROMPT_VERSION,
        metrics=computed,
        limits_note=_limits_note(records, errors),
    )
