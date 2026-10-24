"""The evaluation summary the Trust Scorecard shows: contract ``evaluation-summary-v1`` (EVAL.md Phase 8).

Built once per run by ``run_eval.py`` from that run's actual report, per-case outcomes and dataset,
validated, and written as ``eval/reports/<stem>.summary.json``. The backend serves the latest one
(``GET /api/evaluations/latest``) after re-validating it here; the frontend only displays it. No
metric is computed outside the evaluation runner.

Every value is either measured in that run or explicitly unavailable with a reason. The summary
says what answered (``source``): an oracle or abstain run is a benchmark of the engine, never a
production or model-accuracy statistic. Representative cases are real records of the run, chosen
by a fixed rule (one per label, a disagreement first if there is one), never written for display.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inkloom_verify.evaluation import metrics
from inkloom_verify.evaluation.limitations import LIMITATIONS, Limitation
from inkloom_verify.evaluation.pipeline_predictor import CaseOutcome
from inkloom_verify.evaluation.report import METRICS, _ratio, baseline_rows, outcome
from inkloom_verify.schemas import EvalRecord

CONTRACT = "evaluation-summary-v1"
PASSAGE_EXCERPT_CHARS = 700
_KIND = {
    "oracle": "benchmark (scripted gold answers)",
    "abstain": "benchmark floor (always abstains)",
    "dry-run": "call count only",
    "openrouter": "live model",
    "replay": "replayed recording",
    "predictions": "saved predictions",
}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricOut(_M):
    key: str
    label: str
    explanation: str
    display: (
        str  # exactly as the Markdown report prints it, so the page and the report never differ
    )
    value: float | None
    numerator: int | None
    denominator: int | None
    unavailable_reason: str | None


class GateOut(_M):
    name: str
    applies_to: str | None
    op: str | None
    current: float | None
    baseline: float | None
    change: float | None
    status: str | None
    enforced: bool
    violated: bool
    note: str


class PassageOut(_M):
    doc_id: str
    title: str | None
    text: str
    truncated: bool


class CitationOut(_M):
    doc_id: str
    quote: str
    resolves: bool
    supports: bool


class ClaimOut(_M):
    text: str
    verdict: str
    requires_human_review: bool
    review_reasons: list[str]


class CorrectionOut(_M):
    status: str
    replacement_text: str | None
    issues: list[str]


class CaseOut(_M):
    record_id: str
    split: str
    content: str
    claims: list[ClaimOut]
    expected: str
    predicted: str
    agrees: bool
    outcome: str
    reason: str | None
    passages: list[PassageOut]
    citations: list[CitationOut]
    corrections: list[CorrectionOut]
    requires_human_review: bool


class EvaluationSummary(_M):
    contract: Literal["evaluation-summary-v1"] = CONTRACT
    state: Literal["available"] = "available"
    report_id: str | None = None
    generated_at: str
    outcome: dict[str, Any]
    source: dict[str, Any]
    dataset: dict[str, Any]
    model: dict[str, Any]
    prompt_versions: dict[str, str] | None
    retrieval: dict[str, Any] | None
    decision_policy: dict[str, Any] | None
    counts: dict[str, int]
    metrics: list[MetricOut] = Field(min_length=8, max_length=8)
    confusion: dict[str, dict[str, int]]
    review: dict[str, Any]
    corrections: dict[str, Any]
    gates: list[GateOut]
    cases: list[CaseOut] = Field(max_length=6)
    limitations: list[Limitation]
    unavailable: dict[str, str]
    stale: bool = False
    stale_reason: str | None = None


class NoEvaluation(_M):
    contract: Literal["evaluation-summary-v1"] = CONTRACT
    state: Literal["none"] = "none"
    reason: str
    how_to_run: str = (
        "cd services/verification && python eval/run_eval.py --verdicts oracle --check-baseline"
    )


class IncompleteEvaluation(_M):
    """The newest run stopped before it finished: shown as such, never as an empty success."""

    contract: Literal["evaluation-summary-v1"] = CONTRACT
    state: Literal["incomplete"] = "incomplete"
    report_id: str | None = None
    generated_at: str
    verdict_source: str | None
    error: str
    limitations: list[Limitation]


class SummaryInvalid(ValueError):
    """A summary file exists but does not satisfy the contract."""


def _excerpt(text: str, start: int, end: int) -> tuple[str, bool]:
    if len(text) <= PASSAGE_EXCERPT_CHARS:
        return text, False
    middle = (start + end) // 2
    lo = max(0, min(middle - PASSAGE_EXCERPT_CHARS // 2, len(text) - PASSAGE_EXCERPT_CHARS))
    return text[lo : lo + PASSAGE_EXCERPT_CHARS], True


def case_out(record: EvalRecord, case: CaseOutcome) -> CaseOut:
    docs = {d.doc_id: d for d in record.references}
    passages, seen = [], set()
    for claim in case.claims:
        for p in claim.evidence[:3]:
            if (p.doc_id, p.start, p.end) in seen or p.doc_id not in docs:
                continue
            seen.add((p.doc_id, p.start, p.end))
            text, cut = _excerpt(docs[p.doc_id].text[p.start : p.end], 0, p.end - p.start)
            passages.append(
                PassageOut(doc_id=p.doc_id, title=docs[p.doc_id].title, text=text, truncated=cut)
            )
    citations = [
        CitationOut(
            doc_id=c.doc_id,
            quote=c.quote,
            resolves=metrics.citation_problem(record, c.doc_id, c.quote, c.start, c.end) is None,
            supports=claim.verdict == record.expected_verdict.value
            and metrics.overlaps_gold(record, c.doc_id, c.start, c.end),
        )
        for claim in case.claims
        for c in claim.citations
    ]
    return CaseOut(
        record_id=record.record_id,
        split=record.split.value,
        content=record.claim_text,
        claims=[
            ClaimOut(
                text=c.statement or c.text,
                verdict=c.verdict,
                requires_human_review=c.requires_human_review,
                review_reasons=c.review_reasons,
            )
            for c in case.claims
        ],
        expected=case.expected,
        predicted=case.predicted,
        agrees=case.expected == case.predicted,
        outcome=case.outcome,
        reason=case.reason,
        passages=passages[:4],
        citations=citations,
        corrections=[
            CorrectionOut(
                status=c.correction.status,
                replacement_text=c.correction.replacement_text,
                issues=c.correction.issues,
            )
            for c in case.claims
            if c.correction
        ],
        requires_human_review=case.requires_human_review,
    )


def representative(cases: dict[str, CaseOutcome], records: dict[str, EvalRecord]) -> list[CaseOut]:
    """One real case per label (SUPPORTED, CONTRADICTED, NOT_ENOUGH_EVIDENCE): a disagreement
    first when that label has one, otherwise the first record by id. Never invented."""
    chosen = []
    for label in ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE"):
        pool = sorted(
            (c for rid, c in cases.items() if c.expected == label and rid in records and c.claims),
            key=lambda c: (c.outcome == "correct", c.record_id),
        )
        if pool:
            chosen.append(case_out(records[pool[0].record_id], pool[0]))
    return chosen


def build_summary(
    report: dict[str, Any], cases: dict[str, CaseOutcome] | None, records: dict[str, EvalRecord]
) -> EvaluationSummary:
    run, v, m = report["run"], report["verdicts"], report["required_metrics"]
    config = run.get("model_configuration") or {}
    policy = run.get("decision_policy") or {}
    return EvaluationSummary(
        generated_at=run["created_at"],
        outcome=outcome(report),
        source={
            "verdict_source": run["verdict_source"],
            "kind": _KIND.get(run["verdict_source"], run["verdict_source"]),
            "is_model_quality": bool(v["is_model_quality"]),
            "benchmark": True,
            "production_statistics": False,
            "git_commit": run.get("git_commit"),
            "engine_version": run.get("engine_version"),
        },
        dataset={
            k: run["dataset"].get(k)
            for k in ("path", "sha256", "records", "locked", "labels", "groups")
        }
        | {"human_reviewed": report.get("datasets", {}).get("human_reviewed")},
        model={
            "provider": config.get("provider"),
            "models": config.get("models"),
            "model_ids": v.get("model_ids") or [],
        },
        prompt_versions=run.get("prompt_versions"),
        retrieval=run.get("retrieval_parameters"),
        decision_policy={"policy": policy.get("policy"), "calibration": policy.get("calibration")}
        if policy
        else None,
        counts={k: int(n) for k, n in m["counts"].items()},
        metrics=[
            MetricOut(
                key=key,
                label=label,
                explanation=what,
                display=_ratio(m.get(key), m["unavailable"].get(key)),
                value=(m.get(key) or {}).get("value"),
                numerator=(m.get(key) or {}).get("numerator"),
                denominator=(m.get(key) or {}).get("denominator"),
                unavailable_reason=m["unavailable"].get(key),
            )
            for key, label, what in METRICS
        ],
        confusion=v["confusion"],
        review=m.get("review") or {},
        corrections=m.get("corrections") or {},
        gates=[GateOut(**row) for row in baseline_rows(report)],
        cases=representative(cases or {}, records),
        limitations=LIMITATIONS,
        unavailable=m["unavailable"],
    )


def incomplete_summary(report: dict[str, Any]) -> IncompleteEvaluation:
    run = report["run"]
    return IncompleteEvaluation(
        generated_at=run["created_at"],
        verdict_source=run.get("verdict_source"),
        error=run["error"],
        limitations=LIMITATIONS,
    )


def latest_summary(
    reports_dir: Path, lock_file: Path | None = None
) -> EvaluationSummary | IncompleteEvaluation | NoEvaluation:
    """The newest ``*.summary.json`` in ``reports_dir``, re-validated; marked stale when the locked
    dataset has changed since. Raises SummaryInvalid if the newest file breaks the contract."""
    files = sorted(reports_dir.glob("*.summary.json")) if reports_dir.is_dir() else []
    if not files:
        return NoEvaluation(reason="No evaluation report has been generated yet.")
    try:
        data = json.loads(files[-1].read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("state") == "incomplete":
            return IncompleteEvaluation.model_validate(data)
        summary = EvaluationSummary.model_validate(data)
    except (OSError, ValueError, ValidationError):
        raise SummaryInvalid(f"{files[-1].name} does not match {CONTRACT}") from None
    if lock_file is not None and lock_file.is_file() and summary.dataset.get("locked"):
        current = (
            json.loads(lock_file.read_text(encoding="utf-8"))["files"]
            .get("eval/dataset.jsonl", {})
            .get("sha256")
        )
        if current and current != summary.dataset.get("sha256"):
            summary = summary.model_copy(
                update={"stale": True, "stale_reason": "eval/dataset.jsonl changed after this run"}
            )
    return summary
