"""The eight metrics EVAL.md requires, computed from an evaluation run's actual results.

Inputs: the labelled records, one prediction per record (``EvalPrediction``), and, from a
full-pipeline run, the per-case outcomes (``cases.jsonl``). Every rate is a ``Ratio`` (numerator,
denominator, value). A rate whose denominator is 0, or whose input does not exist for this run,
is **unavailable**: its value is ``None`` (printed "n/a") and ``unavailable`` says why. It is
never reported as 0.

**Positive class: CONTRADICTED.** For every evaluated record (N):

* TP: labelled CONTRADICTED, predicted CONTRADICTED
* FP: labelled SUPPORTED or NOT_ENOUGH_EVIDENCE, predicted CONTRADICTED
* FN: labelled CONTRADICTED, predicted anything else (SUPPORTED, NOT_ENOUGH_EVIDENCE, ERROR, or
  no prediction at all)
* TN: labelled SUPPORTED or NOT_ENOUGH_EVIDENCE, predicted anything but CONTRADICTED

A missing prediction is scored as ERROR, so it is never a positive: it is an FN on a
CONTRADICTED record and a TN elsewhere, and is counted in ``counts.missing_predictions``.

1. precision = TP / (TP + FP); unavailable if CONTRADICTED was never predicted.
2. recall = TP / (TP + FN); unavailable if no record is labelled CONTRADICTED.
3. false-positive rate = FP / (FP + TN): the share of non-CONTRADICTED records wrongly flagged.
4. false-negative rate = FN / (TP + FN) = 1 - recall: the share of contradictions missed.
5. citation validity = valid citations / all citations in the predictions. A citation is valid
   only if it **resolves** (its quote is exactly the text at its span in one of the record's
   reference documents, of the same version: ``metrics.citation_problem``) **and supports** the
   claim: the record is labelled SUPPORTED or CONTRADICTED, the prediction has that same
   verdict, and the cited span overlaps the annotated gold evidence. Unavailable when no citation
   was given. ``citation_resolution`` (resolves only) is reported beside it. A non-empty quote is
   never enough, and a citation on a NOT_ENOUGH_EVIDENCE record supports nothing.
6. retrieval recall@5 = records whose gold evidence is overlapped by at least one of the five
   top-ranked passages / records with gold evidence. *Relevant* means sharing at least one
   character with an annotated gold span in the same document. Records without gold evidence
   (NOT_ENOUGH_EVIDENCE) are excluded and counted; an empty retrieval is a miss.
7. human-review share = records routed to a person / records with a pipeline outcome. Needs
   per-case outcomes (``--pipeline full``); a record the pipeline could not decide is routed.
   Records with a prediction but no outcome are excluded and counted.
8. correction traceability = traceable proposals / proposed corrections. A proposal is traceable
   when it cites at least one quote, every cited quote resolves in the record's references and is
   among the claim's own accepted citations (the permitted evidence), and every word or number
   the replacement adds to the original appears in the cited quotes. Unavailable when nothing was
   proposed. Claims without a correction attempt are "not applicable" and counted.

The traceability check is lexical: it proves each added word is *present* in the evidence, not
that the corrected sentence means what the evidence means.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from inkloom_verify.chunking import ChunkingConfig
from inkloom_verify.evaluation import metrics
from inkloom_verify.evaluation.metrics import Ratio
from inkloom_verify.evaluation.pipeline_predictor import CaseOutcome
from inkloom_verify.evaluation.runner import EvalPrediction, _eval_claim, load_predictions, load_records
from inkloom_verify.retrieval import BM25Retriever, RetrievalConfig
from inkloom_verify.schemas import EvalRecord, Verdict

POSITIVE = Verdict.CONTRADICTED
LABELS = (Verdict.SUPPORTED, Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE)
RECALL_K = 5
_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+|[€$£%]", re.UNICODE)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Untraceable(_Model):
    record_id: str
    claim_id: str
    reasons: list[str]


class RequiredMetrics(_Model):
    positive_class: str = POSITIVE.value
    counts: dict[str, int]
    contradicted_precision: Ratio | None
    contradicted_recall: Ratio | None
    false_positive_rate: Ratio | None
    false_negative_rate: Ratio | None
    citation_validity: Ratio | None
    citation_resolution: Ratio | None
    citation_failures: dict[str, Any]
    retrieval_recall_at_5: Ratio | None
    retrieval: dict[str, Any]
    human_review_share: Ratio | None
    review: dict[str, Any]
    correction_traceability: Ratio | None
    corrections: dict[str, Any]
    unavailable: dict[str, str]
    # Reliability additions (Member 2 audit, 2026-10-24). Defaults keep older saved reports loadable.
    # Provider failure rate: records whose prediction is ERROR (provider failure, invalid output,
    # budget refusal, missing prediction) / evaluated records.
    provider_failure_rate: Ratio | None = None
    # Wall-clock seconds per case from the full pipeline (cases.jsonl): n, mean, p50, p95, max.
    # It includes provider time only when a live provider answered; scripted runs time local code.
    latency: dict[str, Any] = {}
    # ERROR predictions (no verdict) by cause, and how many of them the confusion counts above hold:
    # an ERROR on a CONTRADICTED record counts as FN (it was not flagged) and on any other record as
    # TN (nothing was wrongly flagged). These are failures, not model decisions; reported so a run
    # full of errors cannot look like a model with a perfect false-positive rate.
    errors: dict[str, Any] = {}


def _rate(numerator: int, denominator: int, name: str, unavailable: dict[str, str], why: str) -> Ratio | None:
    if denominator == 0:
        unavailable[name] = why
        return None
    return metrics.ratio(numerator, denominator)


def _tokens(text: str) -> list[str]:
    return [t.casefold() for t in _TOKEN.findall(text)]


def traceability_problems(record: EvalRecord, claim_citations: Iterable[Mapping[str, Any]], correction: Mapping[str, Any],
                          original: str) -> list[str]:
    """Why a proposed correction is not traceable to its permitted evidence; empty if it is."""
    problems = []
    cited = list(correction.get("citations") or [])
    if not cited:
        problems.append("no_citation")
    permitted = {(c["doc_id"], c["start"], c["end"]) for c in claim_citations}
    usable = []  # only quotes that resolve and are permitted count as evidence for the added words
    for c in cited:
        if metrics.citation_problem(record, c["doc_id"], c["quote"], c["start"], c["end"]) is not None:
            problems.append("citation_not_in_references")
        elif (c["doc_id"], c["start"], c["end"]) not in permitted:
            problems.append("citation_not_among_claim_evidence")
        else:
            usable.append(c)
    evidence = Counter(t for c in usable for t in _tokens(c["quote"]))
    added = [t for t in _tokens(correction.get("replacement_text") or "") if t not in set(_tokens(original))]
    problems += [f"unsupported:{t}" for t in dict.fromkeys(added) if t not in evidence]
    if not (correction.get("replacement_text") or "").strip():
        problems.append("empty_replacement")
    return problems


def compute(
    records: Sequence[EvalRecord],
    predictions: Mapping[str, EvalPrediction],
    cases: Mapping[str, CaseOutcome | Mapping[str, Any]] | None = None,
    chunking: ChunkingConfig | None = None,
    retrieval: RetrievalConfig | None = None,
) -> RequiredMetrics:
    """The eight metrics for one run (see the module docstring for every definition)."""
    unavailable: dict[str, str] = {}
    counts = Counter({"evaluated": 0, "tp": 0, "fp": 0, "fn": 0, "tn": 0, "missing_predictions": 0,
                      "error_predictions": 0, "invalid_labels": 0})
    citation_fail = Counter()
    error_codes: Counter[str] = Counter()
    error_examples: dict[str, str] = {}
    errors_in = Counter()
    valid = resolved = total_citations = 0
    evaluated: list[EvalRecord] = []
    for record in records:
        if record.expected_verdict not in LABELS:  # the contract already forbids this; never scored if it happens
            counts["invalid_labels"] += 1
            continue
        evaluated.append(record)
        counts["evaluated"] += 1
        prediction = predictions.get(record.record_id)
        if prediction is None:
            counts["missing_predictions"] += 1
        predicted = prediction.verdict if prediction else Verdict.ERROR
        counts["error_predictions"] += predicted is Verdict.ERROR
        if predicted is Verdict.ERROR:
            code = "MISSING_PREDICTION" if prediction is None else (prediction.error_code or "UNSPECIFIED")
            error_codes[code] += 1
            if prediction is not None and prediction.error_message and code not in error_examples:
                error_examples[code] = prediction.error_message[:200]
            errors_in["fn" if record.expected_verdict is POSITIVE else "tn"] += 1
        positive_label, positive_prediction = record.expected_verdict is POSITIVE, predicted is POSITIVE
        counts["tp" if positive_label and positive_prediction else "fn" if positive_label else
               "fp" if positive_prediction else "tn"] += 1
        if prediction is None:
            continue
        if predicted in (Verdict.SUPPORTED, Verdict.CONTRADICTED) and not prediction.citations:
            citation_fail["definite_verdict_without_citation"] += 1
        for c in prediction.citations:
            total_citations += 1
            problem = metrics.citation_problem(record, c.doc_id, c.quote, c.quote_span.start, c.quote_span.end, c.doc_text_sha256)
            if problem is not None:
                citation_fail[f"does_not_resolve:{problem.value}"] += 1
                continue
            resolved += 1
            if predicted not in (Verdict.SUPPORTED, Verdict.CONTRADICTED):
                citation_fail["cited_on_abstention_or_error"] += 1
            elif not record.gold_evidence:
                citation_fail["no_supporting_evidence_exists"] += 1
            elif predicted is not record.expected_verdict:
                citation_fail["supports_a_different_verdict"] += 1
            elif not metrics.overlaps_gold(record, c.doc_id, c.quote_span.start, c.quote_span.end):
                citation_fail["not_the_annotated_evidence"] += 1
            else:
                valid += 1
    counts["unexpected_predictions"] = len(set(predictions) - {r.record_id for r in records})

    tp, fp, fn, tn = counts["tp"], counts["fp"], counts["fn"], counts["tn"]
    precision = _rate(tp, tp + fp, "contradicted_precision", unavailable, "CONTRADICTED was never predicted")
    recall = _rate(tp, tp + fn, "contradicted_recall", unavailable, "no record is labelled CONTRADICTED")
    fpr = _rate(fp, fp + tn, "false_positive_rate", unavailable, "no record is labelled SUPPORTED or NOT_ENOUGH_EVIDENCE")
    fnr = _rate(fn, tp + fn, "false_negative_rate", unavailable, "no record is labelled CONTRADICTED")
    validity = _rate(valid, total_citations, "citation_validity", unavailable, "no citation was given")
    resolution = _rate(resolved, total_citations, "citation_resolution", unavailable, "no citation was given")

    # 6. Retrieval recall@5: the engine's retriever, run on each record with the run's settings.
    chunking = chunking or ChunkingConfig()
    config = (retrieval or RetrievalConfig()).model_copy(update={"top_k": RECALL_K})
    hits = with_gold = empty = 0
    misses = []
    for record in evaluated:
        if not record.gold_evidence:
            continue
        with_gold += 1
        passages = BM25Retriever(record.references, chunking=chunking, config=config).retrieve(_eval_claim(record))
        empty += not passages
        if metrics.gold_spans_covered(record, ((p.doc_id, p.span) for p in passages[:RECALL_K])):
            hits += 1
        else:
            misses.append(record.record_id)
    recall_at_5 = _rate(hits, with_gold, "retrieval_recall_at_5", unavailable, "no record has gold evidence")
    retrieval_info = {"k": RECALL_K, "with_gold_evidence": with_gold, "excluded_without_gold_evidence": len(evaluated) - with_gold,
                      "empty_results": empty, "misses": misses, "chunking": chunking.model_dump(mode="json"),
                      "retrieval": config.model_dump(mode="json")}

    # 7 and 8 need the full pipeline's per-case outcomes.
    outcomes = {k: (v if isinstance(v, CaseOutcome) else CaseOutcome.model_validate(v)) for k, v in (cases or {}).items()}
    by_id = {r.record_id: r for r in evaluated}
    review: dict[str, Any] = {}
    corrections: dict[str, Any] = {}
    share = traceability = None
    if not outcomes:
        unavailable["human_review_share"] = "no per-case pipeline outcomes in this run (needs --pipeline full with a provider)"
        unavailable["correction_traceability"] = "no per-case pipeline outcomes in this run (needs --pipeline full with a provider)"
    else:
        considered = [by_id[k] for k in by_id if k in outcomes]
        routed = [r for r in considered if outcomes[r.record_id].requires_human_review]
        share = _rate(len(routed), len(considered), "human_review_share", unavailable, "no evaluated record has an outcome")
        auto = [r for r in considered if not outcomes[r.record_id].requires_human_review]
        review = {
            "records_with_outcome": len(considered),
            "excluded_without_outcome": len(evaluated) - len(considered),
            "routed_by_label": dict(Counter(r.expected_verdict.value for r in routed)),
            "auto_cleared": len(auto),
            # The safety number: cleared without a person although the label is not SUPPORTED.
            "auto_cleared_but_not_supported": [r.record_id for r in auto if r.expected_verdict is not Verdict.SUPPORTED],
            "auto_cleared_not_supported_count": sum(1 for r in auto if r.expected_verdict is not Verdict.SUPPORTED),
        }
        proposed, traceable, untraceable = 0, 0, []
        statuses = Counter()
        not_applicable = 0
        for record_id, outcome in outcomes.items():
            record = by_id.get(record_id)
            if record is None:
                continue
            for claim in outcome.claims:
                if claim.correction is None:
                    not_applicable += 1
                    continue
                statuses[claim.correction.status] += 1
                if claim.correction.status != "proposed":
                    continue
                proposed += 1
                problems = traceability_problems(record, [c.model_dump() for c in claim.citations], claim.correction.model_dump(),
                                                 claim.correction.original_text or "")
                if problems:
                    untraceable.append(Untraceable(record_id=record_id, claim_id=claim.claim_id, reasons=problems).model_dump())
                else:
                    traceable += 1
        traceability = _rate(traceable, proposed, "correction_traceability", unavailable, "no correction was proposed")
        corrections = {"proposed": proposed, "traceable": traceable, "untraceable": untraceable,
                       "attempts_by_status": dict(statuses), "claims_not_applicable": not_applicable}

    failure_rate = _rate(counts["error_predictions"], counts["evaluated"], "provider_failure_rate", unavailable,
                         "no record was evaluated")
    timings = sorted(o.seconds for o in outcomes.values())
    if timings:
        latency = {"n": len(timings), "mean_seconds": round(sum(timings) / len(timings), 4),
                   "p50_seconds": _percentile(timings, 50), "p95_seconds": _percentile(timings, 95),
                   "max_seconds": timings[-1]}
    else:
        latency = {}
        unavailable["latency"] = "no per-case timings (only full-pipeline runs record them, in cases.jsonl)"

    errors_info = {"by_code": dict(error_codes.most_common()), "example_messages": error_examples,
                   "counted_as_fn": errors_in["fn"], "counted_as_tn": errors_in["tn"]} if error_codes else {}

    return RequiredMetrics(
        provider_failure_rate=failure_rate, latency=latency, errors=errors_info,
        counts=dict(counts), contradicted_precision=precision, contradicted_recall=recall, false_positive_rate=fpr,
        false_negative_rate=fnr, citation_validity=validity, citation_resolution=resolution,
        citation_failures={"citations": total_citations, "valid": valid, "resolved": resolved, **dict(citation_fail)},
        retrieval_recall_at_5=recall_at_5, retrieval=retrieval_info, human_review_share=share, review=review,
        correction_traceability=traceability, corrections=corrections, unavailable=unavailable,
    )


def _percentile(sorted_values: list[float], pct: int) -> float:
    """Nearest-rank percentile of an already sorted, non-empty list."""
    rank = max(1, -(-pct * len(sorted_values) // 100))  # ceil(pct/100 * n), at least 1
    return sorted_values[rank - 1]


def _fmt(r: Ratio | None, name: str, m: RequiredMetrics) -> str:
    if r is None:
        return f"unavailable ({m.unavailable.get(name, 'not measured')})"
    return f"{r.value:.1%} ({r.numerator}/{r.denominator})"


def markdown(m: RequiredMetrics) -> str:
    c = m.counts
    rows = [
        ("1. Precision (CONTRADICTED)", "TP / (TP + FP)", m.contradicted_precision, "contradicted_precision"),
        ("2. Recall (CONTRADICTED)", "TP / (TP + FN)", m.contradicted_recall, "contradicted_recall"),
        ("3. False-positive rate", "FP / (FP + TN)", m.false_positive_rate, "false_positive_rate"),
        ("4. False-negative rate", "FN / (TP + FN)", m.false_negative_rate, "false_negative_rate"),
        ("5. Citation validity", "resolving and supporting citations / all citations", m.citation_validity, "citation_validity"),
        ("   Citation resolution", "resolving citations / all citations", m.citation_resolution, "citation_resolution"),
        ("6. Retrieval recall@5", "records with gold evidence in the top 5 / records with gold evidence",
         m.retrieval_recall_at_5, "retrieval_recall_at_5"),
        ("7. Human-review share", "records routed to review / records with a pipeline outcome", m.human_review_share,
         "human_review_share"),
        ("8. Correction traceability", "traceable proposals / proposed corrections", m.correction_traceability,
         "correction_traceability"),
        ("   Provider failure rate", "ERROR predictions / evaluated records", m.provider_failure_rate,
         "provider_failure_rate"),
    ]
    lines = ["## Required metrics (positive class: CONTRADICTED)", "",
             f"Evaluated {c['evaluated']} records · TP {c['tp']} · FP {c['fp']} · FN {c['fn']} · TN {c['tn']} · "
             f"missing predictions {c['missing_predictions']} · ERROR predictions {c['error_predictions']} · "
             f"invalid labels {c['invalid_labels']} · unexpected predictions {c['unexpected_predictions']}", "",
             "| Metric | Formula | Value |", "|---|---|---|"]
    lines += [f"| {name} | {formula} | {_fmt(r, key, m)} |" for name, formula, r, key in rows]
    if m.errors:
        lines += ["", f"No verdict (ERROR) by cause: {m.errors['by_code']}. Of these, {m.errors['counted_as_fn']} are inside FN "
                  f"and {m.errors['counted_as_tn']} inside TN: failures, not model decisions."]
    lat = m.latency
    lines += ["", ("Latency per case (wall clock, seconds; includes provider time only for live runs): "
                   f"n {lat['n']} · mean {lat['mean_seconds']} · p50 {lat['p50_seconds']} · p95 {lat['p95_seconds']} · "
                   f"max {lat['max_seconds']}") if lat else
              f"Latency: unavailable ({m.unavailable.get('latency', 'not measured')})"]
    cf = {k: v for k, v in m.citation_failures.items() if k not in ("citations", "valid", "resolved")}
    lines += ["", f"Citation failures: {cf or 'none'}",
              f"Retrieval: {m.retrieval['with_gold_evidence']} records with gold evidence, "
              f"{m.retrieval['excluded_without_gold_evidence']} excluded (no gold evidence), "
              f"{m.retrieval['empty_results']} empty retrievals, misses {m.retrieval['misses'] or 'none'}"]
    if m.review:
        lines.append(f"Review: {m.review['records_with_outcome']} records with an outcome, "
                     f"{m.review['excluded_without_outcome']} excluded (no outcome); auto-cleared {m.review['auto_cleared']}; "
                     f"auto-cleared although not SUPPORTED: {m.review['auto_cleared_but_not_supported'] or 'none'}")
    if m.corrections:
        lines.append(f"Corrections: {m.corrections['attempts_by_status'] or 'no attempts'}; "
                     f"{m.corrections['claims_not_applicable']} claims not applicable; untraceable: "
                     + (", ".join(f"{u['record_id']} {u['reasons']}" for u in m.corrections["untraceable"]) or "none"))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Compute the metrics from saved files: a dataset, predictions and (optionally) cases."""
    parser = argparse.ArgumentParser(prog="python -m inkloom_verify.evaluation.required_metrics")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--title", default="Required metrics")
    parser.add_argument("--note", default="", help="a line printed under the title, e.g. what the inputs are")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    cases = None
    if args.cases:
        cases = {}
        for line in args.cases.read_text(encoding="utf-8").splitlines():
            if line.strip():
                outcome = CaseOutcome.model_validate_json(line)
                cases[outcome.record_id] = outcome
    result = compute(load_records(args.dataset), load_predictions(args.predictions), cases)
    text = f"# {args.title}\n\n" + (f"{args.note}\n\n" if args.note else "") + markdown(result)
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
        (args.out.with_suffix(".json")).write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
