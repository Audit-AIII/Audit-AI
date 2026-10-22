"""Command line: ``python -m inkloom_verify.evaluation --help``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inkloom_verify.chunking import ChunkingConfig
from inkloom_verify.evaluation.metrics import GOLD_CLASSES, PREDICTED_CLASSES
from inkloom_verify.evaluation.runner import BASELINES, EvalReport, EvaluationInputError, run
from inkloom_verify.providers.base import ProviderError
from inkloom_verify.providers.openrouter import OpenRouterProvider
from inkloom_verify.retrieval import RetrievalConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m inkloom_verify.evaluation", description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="labelled EvalRecord JSONL file")
    parser.add_argument("--split", choices=["all", "dev", "heldout"], default="all")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--predictions", type=Path, help="EvalPrediction JSONL file from the system under test")
    source.add_argument("--baseline", choices=sorted(BASELINES), help="built-in baseline instead of a predictions file")
    source.add_argument(
        "--verifier",
        choices=["openrouter"],
        help="run the engine live (retrieval, LLM verifier, citation guard); needs OPENROUTER_API_KEY and INKLOOM_LLM_MODELS",
    )
    parser.add_argument("--no-retrieval", action="store_true", help="skip the retrieval metrics")
    parser.add_argument("--top-k", type=int, default=RetrievalConfig().top_k, help="passages retrieved per claim")
    parser.add_argument(
        "--chunking-strategy", choices=["tokens", "sentences"], default="tokens",
        help="how reference documents are split into passages (default: 200-400 token chunks)",
    )
    parser.add_argument("--examples", type=int, default=5, help="failure examples kept per failure kind")
    parser.add_argument("--out", type=Path, help="write the full JSON report here")
    parser.add_argument("--save-predictions", type=Path, help="write the predictions as JSONL here")
    return parser


def summary(report: EvalReport) -> str:
    m, r = report.manifest, report.results
    lines = [
        f"Dataset   {m.dataset.path}  split={m.dataset.split}  sha256={m.dataset.sha256[:12]}",
        f"          {m.dataset.records_evaluated} of {m.dataset.records_in_file} records evaluated; "
        f"human-reviewed labels: {m.dataset.human_reviewed}",
        f"Predictor {m.predictor.kind}: {m.predictor.name}"
        + (f"  models={','.join(m.predictor.model_ids)}" if m.predictor.model_ids else ""),
        f"Engine    {m.environment.engine_version}  git={m.environment.git_commit or 'unknown'}"
        + ("  (uncommitted changes)" if m.environment.git_dirty else ""),
        "",
        f"Examples            {r.counts.examples}  (missing predictions: {r.counts.missing_predictions}, "
        f"unexpected: {r.counts.unexpected_predictions})",
        f"Verdict accuracy    {r.verdict.accuracy}",
        f"Macro F1            {'n/a' if r.verdict.macro_f1.value is None else f'{r.verdict.macro_f1.value:.3f}'}",
        f"False SUPPORTED     {r.verdict.false_supported_rate}   (labelled not SUPPORTED, predicted SUPPORTED)",
        f"Abstention rate     {r.verdict.abstention_rate}",
        f"Error rate          {r.verdict.error_rate}",
        "",
        "Per class               precision            recall               F1",
    ]
    for cls in GOLD_CLASSES:
        c = r.verdict.per_class[cls]
        f1 = "n/a" if c.f1 is None else f"{c.f1:.3f}"
        lines.append(f"  {cls.value:<22}{str(c.precision):<21}{str(c.recall):<21}{f1}")
    lines += ["", "Confusion (rows = label, columns = prediction)"]
    lines.append("  " + " " * 20 + "".join(f"{p.value[:12]:>14}" for p in PREDICTED_CLASSES))
    for gold in GOLD_CLASSES:
        lines.append(f"  {gold.value:<20}" + "".join(f"{r.verdict.confusion[gold][p]:>14}" for p in PREDICTED_CLASSES))
    lines += [
        "",
        f"Citations           {r.citations.citations_total} given",
        f"  validity          {r.citations.validity}   (quote is the verbatim text at its span)",
        f"  definite + valid  {r.citations.definite_with_valid_citation}",
        f"  grounding         {r.citations.grounding}   (correct definite verdicts citing gold evidence)",
        f"  fully correct     {r.citations.fully_correct}   (right verdict and right evidence)",
        "",
        "Scorecard candidates (definitions not yet agreed)",
        f"  catch rate        {r.scorecard_candidates.catch_rate}",
        f"  false positives   {r.scorecard_candidates.false_positive_rate}",
    ]
    if r.retrieval is not None:
        lines += [
            "",
            f"Retrieval (BM25, top_k={r.retrieval.top_k})",
            f"  evidence hit      {r.retrieval.evidence_hit_rate}   (a retrieved passage overlaps gold evidence)",
            f"  full coverage     {r.retrieval.full_evidence_coverage}",
            f"  no passages       {r.retrieval.empty_results}",
        ]
    lines += ["", "Accuracy by split"] + [f"  {s.value:<20}{v}" for s, v in r.by_split.items()]
    lines += ["", "Accuracy by category"] + [f"  {c.value:<22}{v}" for c, v in r.by_category.items()]
    lines += ["", "Failures"]
    for kind, count in r.failures.counts.items():
        if count:
            lines.append(f"  {kind.value:<26}{count}")
            for example in r.failures.examples.get(kind, []):
                lines.append(f"    {example.record_id}: {example.claim_text[:70]}  [{example.detail}]")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        provider = OpenRouterProvider.from_env() if args.verifier == "openrouter" else None
        report = run(
            args.dataset,
            split=args.split,
            predictions_path=args.predictions,
            baseline=args.baseline,
            engine_provider=provider,
            retrieval=None if args.no_retrieval else (
                ChunkingConfig(strategy=args.chunking_strategy), RetrievalConfig(top_k=args.top_k)
            ),
            max_examples=args.examples,
            save_predictions=args.save_predictions,
        )
    except ProviderError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (EvaluationInputError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
