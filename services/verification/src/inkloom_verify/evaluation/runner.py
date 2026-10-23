"""Runs the claim-verification evaluation: labels in, predictions in, report out.

Labels (``EvalRecord``) and predictions (``EvalPrediction``) are separate files and separate
models. A prediction cannot carry a label (unknown fields are rejected), and the runner never
writes to the dataset.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from importlib import metadata
from pathlib import Path
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inkloom_verify import __version__
from inkloom_verify.chunking import ChunkingConfig
from inkloom_verify.evaluation import metrics
from inkloom_verify.evaluation.metrics import DEFINITE, GOLD_CLASSES, CitationProblem, ClassMetrics, MacroF1, Ratio
from inkloom_verify.providers.base import LLMProvider
from inkloom_verify.retrieval import BM25Retriever, RetrievalConfig
from inkloom_verify.schemas import CONTRACT_VERSION, Claim, EvalCategory, EvalRecord, EvalSplit, SourceSpan, Verdict


class EvaluationInputError(ValueError):
    """A dataset or predictions file cannot be used as given."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Predictions -------------------------------------------------------------------------------


class PredictedSpan(_Model):
    # Not a SourceSpan: an empty or reversed span is a prediction to be scored as invalid,
    # not a file to be rejected.
    start: Annotated[int, Field(strict=True)]
    end: Annotated[int, Field(strict=True)]


class PredictedCitation(_Model):
    doc_id: str
    quote: str
    quote_span: PredictedSpan
    doc_text_sha256: str | None = None
    passage_id: str | None = None


class EvalPrediction(_Model):
    """One system output for one EvalRecord (one JSONL line of a predictions file)."""

    record_id: str
    verdict: Verdict
    citations: list[PredictedCitation] = []
    model_id: str | None = None
    prompt_version: str | None = None


class Predictor(Protocol):
    name: str

    def predict(self, record: EvalRecord) -> EvalPrediction: ...


class AbstainBaseline:
    """Answers NOT_ENOUGH_EVIDENCE for every claim, with no citations.

    A floor, not a verifier: it shows what the metrics look like for a system that never commits.
    """

    name = "baseline-abstain"

    def predict(self, record: EvalRecord) -> EvalPrediction:
        return EvalPrediction(record_id=record.record_id, verdict=Verdict.NOT_ENOUGH_EVIDENCE)


BASELINES: dict[str, type[AbstainBaseline]] = {"abstain": AbstainBaseline}


def _eval_claim(record: EvalRecord) -> Claim:
    return Claim(claim_id="clm_eval", text=record.claim_text, source_span=SourceSpan(start=0, end=len(record.claim_text)))


class EngineVerifierPredictor:
    """The engine itself: BM25 retrieval over the record's references, then the LLM verifier and
    citation guard. It sees the claim text and references only, never the label."""

    def __init__(
        self,
        provider: LLMProvider,
        chunking: ChunkingConfig | None = None,
        retrieval: RetrievalConfig | None = None,
    ) -> None:
        self.provider = provider
        self.name = f"engine/{provider.name}"
        self.chunking = chunking or ChunkingConfig()
        self.retrieval = retrieval or RetrievalConfig()
        self.models: set[str] = set()

    def predict(self, record: EvalRecord) -> EvalPrediction:
        # Imported here: verification depends on extraction and providers, which the rest of the
        # harness does not need.
        from inkloom_verify.verification import ClaimVerifier, verify_claim

        verifier = ClaimVerifier(self.provider, record.references)
        retriever = BM25Retriever(record.references, chunking=self.chunking, config=self.retrieval)
        result = verify_claim(_eval_claim(record), retriever, verifier)
        self.models |= verifier.models_used
        return EvalPrediction(
            record_id=record.record_id,
            verdict=result.verdict,
            citations=[
                PredictedCitation(
                    doc_id=c.doc_id,
                    quote=c.quote,
                    quote_span=PredictedSpan(start=c.quote_span.start, end=c.quote_span.end),
                    doc_text_sha256=c.doc_text_sha256,
                    passage_id=c.passage_id,
                )
                for c in result.citations
            ],
            model_id=",".join(sorted(verifier.models_used)) or None,
            prompt_version=verifier.prompt.version if verifier.prompt_sent else None,  # the version actually sent
        )


# --- Loading -----------------------------------------------------------------------------------


def _jsonl(path: Path) -> Iterable[tuple[int, dict]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvaluationInputError(f"cannot read {path}: {error.strerror}") from error
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvaluationInputError(f"{path}:{number}: not valid JSON ({error.msg})") from error
        if not isinstance(value, dict):
            raise EvaluationInputError(f"{path}:{number}: expected a JSON object")
        yield number, value


def _validation_summary(error: ValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first["loc"]) or "record"
    return f"{location}: {first['msg']}"


def load_records(path: Path) -> list[EvalRecord]:
    records: list[EvalRecord] = []
    seen: set[str] = set()
    for number, value in _jsonl(path):
        try:
            record = EvalRecord.model_validate(value)
        except ValidationError as error:
            raise EvaluationInputError(f"{path}:{number}: {_validation_summary(error)}") from error
        if record.record_id in seen:
            raise EvaluationInputError(f"{path}:{number}: duplicate record_id {record.record_id}")
        seen.add(record.record_id)
        records.append(record)
    if not records:
        raise EvaluationInputError(f"{path}: no records")
    return records


def load_predictions(path: Path) -> dict[str, EvalPrediction]:
    predictions: dict[str, EvalPrediction] = {}
    for number, value in _jsonl(path):
        try:
            prediction = EvalPrediction.model_validate(value)
        except ValidationError as error:
            raise EvaluationInputError(f"{path}:{number}: {_validation_summary(error)}") from error
        if prediction.record_id in predictions:
            raise EvaluationInputError(f"{path}:{number}: duplicate prediction for {prediction.record_id}")
        predictions[prediction.record_id] = prediction
    return predictions


def select_split(records: Sequence[EvalRecord], split: str) -> list[EvalRecord]:
    if split == "all":
        return list(records)
    wanted = EvalSplit(split)
    return [r for r in records if r.split is wanted]


# --- Report ------------------------------------------------------------------------------------


class FailureKind(str, Enum):
    MISSING_PREDICTION = "missing_prediction"  # no prediction for the record; scored as ERROR
    ERROR_VERDICT = "error_verdict"  # the system returned ERROR
    FALSE_SUPPORTED = "false_supported"  # SUPPORTED, but the label is CONTRADICTED or NOT_ENOUGH_EVIDENCE
    FALSE_CONTRADICTION = "false_contradiction"  # CONTRADICTED, but the label is SUPPORTED or NOT_ENOUGH_EVIDENCE
    MISSED_CONTRADICTION = "missed_contradiction"  # NOT_ENOUGH_EVIDENCE, but the label is CONTRADICTED
    OVER_ABSTENTION = "over_abstention"  # NOT_ENOUGH_EVIDENCE, but the label is SUPPORTED
    UNCITED_DEFINITE_VERDICT = "uncited_definite_verdict"  # SUPPORTED/CONTRADICTED with no citation
    INVALID_CITATION = "invalid_citation"  # a citation does not quote the references verbatim
    UNGROUNDED_CITATION = "ungrounded_citation"  # valid quotes, but none overlaps the gold evidence
    CITATION_ON_ABSTENTION = "citation_on_abstention"  # NOT_ENOUGH_EVIDENCE or ERROR with citations


class FailureExample(_Model):
    record_id: str
    split: EvalSplit
    kind: FailureKind
    expected: Verdict
    predicted: Verdict | None
    claim_text: str
    detail: str


class VerdictMetrics(_Model):
    accuracy: Ratio
    confusion: dict[Verdict, dict[Verdict, int]]
    per_class: dict[Verdict, ClassMetrics]
    macro_f1: MacroF1
    abstention_rate: Ratio
    error_rate: Ratio
    false_supported_rate: Ratio


class CitationMetrics(_Model):
    citations_total: int
    validity: Ratio
    problems: dict[CitationProblem, int]
    definite_with_valid_citation: Ratio
    grounding: Ratio
    fully_correct: Ratio


class ScorecardCandidates(_Model):
    catch_rate: Ratio
    false_positive_rate: Ratio
    definitions: str


class RetrievalMetrics(_Model):
    top_k: int
    chunking: dict[str, int | str]
    config: dict[str, float | int | bool]
    evidence_hit_rate: Ratio
    full_evidence_coverage: Ratio
    empty_results: Ratio


class DatasetInfo(_Model):
    path: str
    sha256: str
    records_in_file: int
    records_evaluated: int
    split: str
    human_reviewed: Ratio


class PredictorInfo(_Model):
    kind: str
    name: str
    path: str | None = None
    sha256: str | None = None
    model_ids: list[str] = []
    prompt_versions: list[str] = []


class EnvironmentInfo(_Model):
    engine_version: str
    contract_version: str
    python: str
    packages: dict[str, str]
    git_commit: str | None
    git_dirty: bool | None


class Manifest(_Model):
    created_at: str
    dataset: DatasetInfo
    predictor: PredictorInfo
    environment: EnvironmentInfo


class Counts(_Model):
    examples: int
    gold: dict[Verdict, int]
    predicted: dict[Verdict, int]
    missing_predictions: int
    unexpected_predictions: int


class Failures(_Model):
    counts: dict[FailureKind, int]
    examples: dict[FailureKind, list[FailureExample]]


class EvalResults(_Model):
    counts: Counts
    verdict: VerdictMetrics
    citations: CitationMetrics
    scorecard_candidates: ScorecardCandidates
    retrieval: RetrievalMetrics | None
    by_split: dict[EvalSplit, Ratio]
    by_category: dict[EvalCategory, Ratio]
    failures: Failures


class EvalReport(_Model):
    manifest: Manifest
    results: EvalResults


SCORECARD_DEFINITIONS = (
    "Flagged = CONTRADICTED or NOT_ENOUGH_EVIDENCE. catch_rate = flagged / labelled CONTRADICTED or "
    "NOT_ENOUGH_EVIDENCE. false_positive_rate = flagged / labelled SUPPORTED. ERROR counts as neither. "
    "Candidate definitions only; not yet agreed with the Trust Scorecard owner."
)


# --- Evaluation --------------------------------------------------------------------------------


def _citation_checks(record: EvalRecord, prediction: EvalPrediction) -> list[tuple[PredictedCitation, CitationProblem | None]]:
    return [
        (
            c,
            metrics.citation_problem(
                record, c.doc_id, c.quote, c.quote_span.start, c.quote_span.end, c.doc_text_sha256
            ),
        )
        for c in prediction.citations
    ]


def _failure_kinds(
    record: EvalRecord,
    prediction: EvalPrediction | None,
    checks: list[tuple[PredictedCitation, CitationProblem | None]],
) -> list[tuple[FailureKind, str]]:
    if prediction is None:
        return [(FailureKind.MISSING_PREDICTION, "no prediction for this record")]
    gold, predicted = record.expected_verdict, prediction.verdict
    found: list[tuple[FailureKind, str]] = []
    if predicted is Verdict.ERROR:
        found.append((FailureKind.ERROR_VERDICT, "the system returned ERROR"))
    elif predicted is not gold:
        kind = {
            Verdict.SUPPORTED: FailureKind.FALSE_SUPPORTED,
            Verdict.CONTRADICTED: FailureKind.FALSE_CONTRADICTION,
            Verdict.NOT_ENOUGH_EVIDENCE: (
                FailureKind.MISSED_CONTRADICTION if gold is Verdict.CONTRADICTED else FailureKind.OVER_ABSTENTION
            ),
        }[predicted]
        found.append((kind, f"expected {gold.value}, got {predicted.value}"))

    valid = [c for c, problem in checks if problem is None]
    invalid = [(c, problem) for c, problem in checks if problem is not None]
    if predicted in DEFINITE and not prediction.citations:
        found.append((FailureKind.UNCITED_DEFINITE_VERDICT, f"{predicted.value} with no citation"))
    if predicted not in DEFINITE and prediction.citations:
        found.append((FailureKind.CITATION_ON_ABSTENTION, f"{predicted.value} with {len(prediction.citations)} citation(s)"))
    if invalid:
        reasons = ", ".join(sorted({p.value for _, p in invalid if p is not None}))
        found.append((FailureKind.INVALID_CITATION, f"{len(invalid)} of {len(checks)} citation(s) invalid: {reasons}"))
    if (
        gold in DEFINITE
        and predicted in DEFINITE
        and valid
        and not any(metrics.overlaps_gold(record, c.doc_id, c.quote_span.start, c.quote_span.end) for c in valid)
    ):
        found.append((FailureKind.UNGROUNDED_CITATION, "valid quotes, none overlapping the gold evidence"))
    return found


def _retrieval_metrics(
    records: Sequence[EvalRecord], chunking: ChunkingConfig, config: RetrievalConfig
) -> RetrievalMetrics:
    hits = full = with_gold = empty = 0
    for record in records:
        retriever = BM25Retriever(record.references, chunking=chunking, config=config)
        passages = retriever.retrieve(_eval_claim(record))
        empty += not passages
        if record.gold_evidence:
            with_gold += 1
            covered = metrics.gold_spans_covered(record, ((p.doc_id, p.span) for p in passages))
            hits += covered > 0
            full += covered == len(record.gold_evidence)
    return RetrievalMetrics(
        top_k=config.top_k,
        chunking=chunking.model_dump(),
        config=config.model_dump(),
        evidence_hit_rate=metrics.ratio(hits, with_gold),
        full_evidence_coverage=metrics.ratio(full, with_gold),
        empty_results=metrics.ratio(empty, len(records)),
    )


def evaluate(
    records: Sequence[EvalRecord],
    predictions: Mapping[str, EvalPrediction],
    *,
    known_record_ids: Iterable[str] | None = None,
    retrieval: tuple[ChunkingConfig, RetrievalConfig] | None = None,
    max_examples: int = 5,
) -> EvalResults:
    """Scores ``predictions`` against ``records``.

    A record without a prediction is scored as ERROR and reported as missing_prediction.
    ``known_record_ids`` (default: ``records``) decides which extra predictions are unexpected,
    so predictions for records outside the evaluated split are not counted as unexpected.
    """
    if not records:
        raise EvaluationInputError("no records to evaluate")
    known = set(known_record_ids) if known_record_ids is not None else {r.record_id for r in records}
    unexpected = len(set(predictions) - known)

    pairs: list[tuple[Verdict, Verdict]] = []
    by_split: dict[EvalSplit, list[bool]] = {}
    by_category: dict[EvalCategory, list[bool]] = {}
    failure_counts: Counter[FailureKind] = Counter()
    failure_examples: dict[FailureKind, list[FailureExample]] = {}
    problems: Counter[CitationProblem] = Counter()
    citations_total = citations_valid = 0
    definite = definite_cited = correct_definite = grounded = fully_correct = missing = 0

    for record in records:
        prediction = predictions.get(record.record_id)
        missing += prediction is None
        predicted = prediction.verdict if prediction is not None else Verdict.ERROR
        gold = record.expected_verdict
        pairs.append((gold, predicted))
        correct = predicted is gold
        by_split.setdefault(record.split, []).append(correct)
        for category in record.categories:
            by_category.setdefault(category, []).append(correct)

        checks = _citation_checks(record, prediction) if prediction is not None else []
        valid = [c for c, problem in checks if problem is None]
        citations_total += len(checks)
        citations_valid += len(valid)
        problems.update(problem for _, problem in checks if problem is not None)

        is_grounded = any(metrics.overlaps_gold(record, c.doc_id, c.quote_span.start, c.quote_span.end) for c in valid)
        if predicted in DEFINITE:
            definite += 1
            definite_cited += bool(valid)
        if correct and gold in DEFINITE:
            correct_definite += 1
            grounded += is_grounded
            fully_correct += is_grounded
        elif correct:
            fully_correct += not checks

        for kind, detail in _failure_kinds(record, prediction, checks):
            failure_counts[kind] += 1
            bucket = failure_examples.setdefault(kind, [])
            if len(bucket) < max_examples:
                bucket.append(
                    FailureExample(
                        record_id=record.record_id,
                        split=record.split,
                        kind=kind,
                        expected=gold,
                        predicted=prediction.verdict if prediction is not None else None,
                        claim_text=record.claim_text,
                        detail=detail,
                    )
                )

    confusion = metrics.confusion_matrix(pairs)
    per_class = {cls: metrics.class_metrics(confusion, cls) for cls in GOLD_CLASSES}
    return EvalResults(
        counts=Counts(
            examples=len(records),
            gold={cls: sum(confusion[cls].values()) for cls in GOLD_CLASSES},
            predicted={p: sum(confusion[g][p] for g in GOLD_CLASSES) for p in metrics.PREDICTED_CLASSES},
            missing_predictions=missing,
            unexpected_predictions=unexpected,
        ),
        verdict=VerdictMetrics(
            accuracy=metrics.accuracy(confusion),
            confusion=confusion,
            per_class=per_class,
            macro_f1=metrics.macro_f1(per_class),
            abstention_rate=metrics.predicted_rate(confusion, Verdict.NOT_ENOUGH_EVIDENCE),
            error_rate=metrics.predicted_rate(confusion, Verdict.ERROR),
            false_supported_rate=metrics.false_supported_rate(confusion),
        ),
        citations=CitationMetrics(
            citations_total=citations_total,
            validity=metrics.ratio(citations_valid, citations_total),
            problems={p: problems.get(p, 0) for p in CitationProblem},
            definite_with_valid_citation=metrics.ratio(definite_cited, definite),
            grounding=metrics.ratio(grounded, correct_definite),
            fully_correct=metrics.ratio(fully_correct, len(records)),
        ),
        scorecard_candidates=ScorecardCandidates(
            catch_rate=metrics.catch_rate(confusion),
            false_positive_rate=metrics.false_positive_rate(confusion),
            definitions=SCORECARD_DEFINITIONS,
        ),
        retrieval=_retrieval_metrics(records, *retrieval) if retrieval is not None else None,
        by_split={split: metrics.ratio(sum(v), len(v)) for split, v in sorted(by_split.items())},
        by_category={c: metrics.ratio(sum(by_category[c]), len(by_category[c])) for c in EvalCategory if c in by_category},
        failures=Failures(
            counts={k: failure_counts.get(k, 0) for k in FailureKind},
            examples=failure_examples,
        ),
    )


# --- Manifest ----------------------------------------------------------------------------------


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def environment_info(cwd: Path) -> EnvironmentInfo:
    packages = {}
    for name in ("pydantic", "rank_bm25", "numpy"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = "not installed"
    commit = _git(["rev-parse", "HEAD"], cwd)
    status = _git(["status", "--porcelain"], cwd) if commit else None
    return EnvironmentInfo(
        engine_version=__version__,
        contract_version=CONTRACT_VERSION,
        python=platform.python_version(),
        packages=packages,
        git_commit=commit,
        git_dirty=bool(status) if status is not None else None,
    )


def run(
    dataset_path: Path,
    *,
    split: str = "all",
    predictions_path: Path | None = None,
    baseline: str | None = None,
    engine_provider: LLMProvider | None = None,
    retrieval: tuple[ChunkingConfig, RetrievalConfig] | None = (ChunkingConfig(), RetrievalConfig()),
    max_examples: int = 5,
    save_predictions: Path | None = None,
) -> EvalReport:
    """Loads the dataset and one source of predictions, evaluates, and records how the run was made.

    The source is a predictions file, a baseline, or the engine run live with ``engine_provider``.
    ``save_predictions`` writes the predictions as JSONL, separate from the labels.
    """
    sources = [predictions_path is not None, baseline is not None, engine_provider is not None]
    if sum(sources) != 1:
        raise EvaluationInputError("give exactly one of a predictions file, a baseline or an engine provider")
    all_records = load_records(dataset_path)
    records = select_split(all_records, split)
    if not records:
        raise EvaluationInputError(f"no records in split {split!r}")

    predictions: dict[str, EvalPrediction] = {}
    predictor: PredictorInfo
    if predictions_path is not None:
        predictions = load_predictions(predictions_path)
        predictor = PredictorInfo(
            kind="predictions_file",
            name=predictions_path.name,
            path=str(predictions_path),
            sha256=file_sha256(predictions_path),
            model_ids=sorted({p.model_id for p in predictions.values() if p.model_id}),
            prompt_versions=sorted({p.prompt_version for p in predictions.values() if p.prompt_version}),
        )
    if baseline is not None:
        if baseline not in BASELINES:
            raise EvaluationInputError(f"unknown baseline {baseline!r}; choose from {', '.join(BASELINES)}")
        model = BASELINES[baseline]()
        predictions = {r.record_id: model.predict(r) for r in records}
        predictor = PredictorInfo(kind="baseline", name=model.name)
    if engine_provider is not None:
        chunking, retrieval_config = retrieval if retrieval is not None else (ChunkingConfig(), RetrievalConfig())
        engine = EngineVerifierPredictor(engine_provider, chunking, retrieval_config)
        predictions = {r.record_id: engine.predict(r) for r in records}
        predictor = PredictorInfo(
            kind="engine",
            name=engine.name,
            model_ids=sorted(engine.models),
            prompt_versions=sorted({p.prompt_version for p in predictions.values() if p.prompt_version}),
        )
    if save_predictions is not None:
        save_predictions.parent.mkdir(parents=True, exist_ok=True)
        save_predictions.write_text(
            "".join(p.model_dump_json(exclude_none=True) + "\n" for p in predictions.values()), encoding="utf-8"
        )

    results = evaluate(
        records,
        predictions,
        known_record_ids=[r.record_id for r in all_records],
        retrieval=retrieval,
        max_examples=max_examples,
    )
    reviewed = sum(1 for r in records if r.reviewed_by)
    return EvalReport(
        manifest=Manifest(
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            dataset=DatasetInfo(
                path=str(dataset_path),
                sha256=file_sha256(dataset_path),
                records_in_file=len(all_records),
                records_evaluated=len(records),
                split=split,
                human_reviewed=metrics.ratio(reviewed, len(records)),
            ),
            predictor=predictor,
            environment=environment_info(dataset_path.resolve().parent),
        ),
        results=results,
    )
