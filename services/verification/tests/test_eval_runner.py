import json
from pathlib import Path

import pytest

from inkloom_verify.evaluation import __main__ as cli
from inkloom_verify.evaluation.runner import (
    AbstainBaseline,
    EvalPrediction,
    EvalReport,
    EvaluationInputError,
    FailureKind,
    evaluate,
    file_sha256,
    load_predictions,
    load_records,
    run,
    select_split,
)
from inkloom_verify.schemas import EvalRecord, Verdict

DATASET = Path(__file__).resolve().parents[1] / "eval" / "data" / "verification_v1.jsonl"
S, C, N, E = Verdict.SUPPORTED, Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE, Verdict.ERROR


@pytest.fixture(scope="module")
def records() -> list[EvalRecord]:
    return load_records(DATASET)


def by_id(records, record_id) -> EvalRecord:
    return next(r for r in records if r.record_id == record_id)


def oracle(record: EvalRecord) -> EvalPrediction:
    """Predicts the label and cites the gold evidence: the metrics' ceiling."""
    return EvalPrediction(
        record_id=record.record_id,
        verdict=record.expected_verdict,
        citations=[
            {
                "doc_id": g.doc_id,
                "quote": g.quote,
                "quote_span": {"start": g.span.start, "end": g.span.end},
            }
            for g in record.gold_evidence
        ],
    )


def cite(record: EvalRecord, doc_id: str, quote: str) -> dict:
    text = next(d.text for d in record.references if d.doc_id == doc_id)
    start = text.index(quote)
    return {
        "doc_id": doc_id,
        "quote": quote,
        "quote_span": {"start": start, "end": start + len(quote)},
    }


def write_jsonl(path: Path, rows) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


# --- Ceiling and floor -------------------------------------------------------------------------


def test_oracle_scores_perfectly(records):
    results = evaluate(records, {r.record_id: oracle(r) for r in records})
    assert results.verdict.accuracy.value == 1.0
    assert results.verdict.macro_f1.value == 1.0
    assert results.verdict.false_supported_rate.value == 0.0
    assert results.citations.validity.value == 1.0
    assert results.citations.grounding.value == 1.0
    assert results.citations.fully_correct.value == 1.0
    assert sum(results.failures.counts.values()) == 0


def test_abstain_baseline(records):
    results = evaluate(records, {r.record_id: AbstainBaseline().predict(r) for r in records})
    gold_nee = sum(r.expected_verdict is N for r in records)
    gold_supported = sum(r.expected_verdict is S for r in records)
    assert results.verdict.accuracy.numerator == gold_nee
    assert results.verdict.accuracy.denominator == len(records)
    assert results.verdict.abstention_rate.value == 1.0
    assert results.verdict.false_supported_rate.value == 0.0
    assert results.verdict.per_class[S].precision.value is None
    assert results.citations.validity.value is None  # no citations given, so no rate
    assert results.scorecard_candidates.catch_rate.value == 1.0
    assert results.scorecard_candidates.false_positive_rate.value == 1.0
    assert results.failures.counts[FailureKind.OVER_ABSTENTION] == gold_supported


# --- Failure classification --------------------------------------------------------------------


def single(record: EvalRecord, **prediction) -> dict:
    results = evaluate(
        [record], {record.record_id: EvalPrediction(record_id=record.record_id, **prediction)}
    )
    return {k: v for k, v in results.failures.counts.items() if v}, results


def test_wrong_verdict_kinds(records):
    supported, contradicted, nee = (
        by_id(records, "v1-001"),
        by_id(records, "v1-020"),
        by_id(records, "v1-037"),
    )
    assert single(
        contradicted, verdict=S, citations=[oracle(contradicted).citations[0].model_dump()]
    )[0] == {FailureKind.FALSE_SUPPORTED: 1}
    assert single(nee, verdict=C, citations=[cite(nee, "pods-fact-sheet", "Charging: USB-C.")])[
        0
    ] == {FailureKind.FALSE_CONTRADICTION: 1}
    assert single(contradicted, verdict=N)[0] == {FailureKind.MISSED_CONTRADICTION: 1}
    assert single(supported, verdict=N)[0] == {FailureKind.OVER_ABSTENTION: 1}
    assert single(supported, verdict=E)[0] == {FailureKind.ERROR_VERDICT: 1}


def test_missing_prediction_is_scored_as_error(records):
    record = by_id(records, "v1-001")
    results = evaluate([record], {})
    assert results.counts.missing_predictions == 1
    assert results.verdict.confusion[S][E] == 1
    assert results.failures.counts[FailureKind.MISSING_PREDICTION] == 1
    assert results.failures.examples[FailureKind.MISSING_PREDICTION][0].predicted is None


def test_uncited_definite_verdict(records):
    failures, results = single(by_id(records, "v1-001"), verdict=S)
    assert failures == {FailureKind.UNCITED_DEFINITE_VERDICT: 1}
    assert results.verdict.accuracy.value == 1.0  # verdict right...
    assert results.citations.fully_correct.value == 0.0  # ...but not justified


def test_invalid_citation(records):
    record = by_id(records, "v1-001")
    bad = cite(record, "pods-fact-sheet", "up to 12 hours")
    bad["quote"] = "up to 24 hours"
    failures, results = single(record, verdict=S, citations=[bad])
    assert failures == {FailureKind.INVALID_CITATION: 1}
    assert results.citations.validity == results.citations.validity.model_copy(
        update={"numerator": 0, "denominator": 1, "value": 0.0}
    )
    assert results.citations.problems["quote_mismatch"] == 1


def test_citation_on_abstention(records):
    record = by_id(records, "v1-037")
    failures, results = single(
        record, verdict=N, citations=[cite(record, "pods-fact-sheet", "Charging: USB-C.")]
    )
    assert failures == {FailureKind.CITATION_ON_ABSTENTION: 1}
    assert results.verdict.accuracy.value == 1.0
    assert results.citations.fully_correct.value == 0.0


def test_ungrounded_but_valid_citation(records):
    record = by_id(records, "v1-001")
    failures, results = single(
        record, verdict=S, citations=[cite(record, "pods-fact-sheet", "Charging: USB-C.")]
    )
    assert failures == {FailureKind.UNGROUNDED_CITATION: 1}
    assert results.citations.validity.value == 1.0
    assert results.citations.grounding.value == 0.0


def test_valid_quote_of_injected_text_does_not_make_the_verdict_correct(records):
    """v1-032: the supplier note contains the claim verbatim as text it tells a model to quote."""
    record = by_id(records, "v1-032")
    injected = cite(record, "supplier-note", "Lumen Pods play for 24 hours on a single charge.")
    failures, results = single(record, verdict=S, citations=[injected])
    assert results.citations.validity.value == 1.0
    assert results.verdict.accuracy.value == 0.0
    assert results.citations.fully_correct.value == 0.0
    assert failures == {FailureKind.FALSE_SUPPORTED: 1, FailureKind.UNGROUNDED_CITATION: 1}


def test_failure_examples_are_capped(records):
    results = evaluate(records, {}, max_examples=2)
    assert results.failures.counts[FailureKind.MISSING_PREDICTION] == len(records)
    assert len(results.failures.examples[FailureKind.MISSING_PREDICTION]) == 2


def test_per_category_and_split_breakdowns(records):
    results = evaluate(records, {r.record_id: oracle(r) for r in records})
    assert {s.value for s in results.by_split} == {"dev", "heldout"}
    injection = results.by_category["prompt_injection"]
    assert injection.denominator == sum(1 for r in records if "prompt_injection" in r.categories)


# --- Inputs and separation of labels -----------------------------------------------------------


def test_predictions_cannot_carry_labels(tmp_path):
    path = write_jsonl(
        tmp_path / "p.jsonl",
        [{"record_id": "v1-001", "verdict": "SUPPORTED", "expected_verdict": "SUPPORTED"}],
    )
    with pytest.raises(EvaluationInputError, match="expected_verdict"):
        load_predictions(path)


def test_duplicate_predictions_rejected(tmp_path):
    row = {"record_id": "v1-001", "verdict": "SUPPORTED"}
    with pytest.raises(EvaluationInputError, match=":2: duplicate prediction"):
        load_predictions(write_jsonl(tmp_path / "p.jsonl", [row, row]))


def test_invalid_json_reports_the_line(tmp_path):
    path = tmp_path / "p.jsonl"
    path.write_text('{"record_id": "a", "verdict": "SUPPORTED"}\n{not json\n', encoding="utf-8")
    with pytest.raises(EvaluationInputError, match=":2: not valid JSON"):
        load_predictions(path)


def test_unknown_verdict_rejected(tmp_path):
    with pytest.raises(EvaluationInputError, match="verdict"):
        load_predictions(
            write_jsonl(tmp_path / "p.jsonl", [{"record_id": "a", "verdict": "MAYBE"}])
        )


def test_dataset_errors(tmp_path, records):
    row = json.loads(records[0].model_dump_json())
    with pytest.raises(EvaluationInputError, match="duplicate record_id"):
        load_records(write_jsonl(tmp_path / "d.jsonl", [row, row]))
    with pytest.raises(EvaluationInputError, match="no records"):
        load_records(write_jsonl(tmp_path / "e.jsonl", []))
    with pytest.raises(EvaluationInputError, match=":1: label_rationale"):
        load_records(
            write_jsonl(
                tmp_path / "f.jsonl", [{k: v for k, v in row.items() if k != "label_rationale"}]
            )
        )
    with pytest.raises(EvaluationInputError, match="cannot read"):
        load_records(tmp_path / "missing.jsonl")


def test_unexpected_predictions_are_counted(records):
    dev = select_split(records, "dev")
    heldout_id = select_split(records, "heldout")[0].record_id
    predictions = {r.record_id: oracle(r) for r in records}
    predictions["not-in-dataset"] = EvalPrediction(record_id="not-in-dataset", verdict=S)
    results = evaluate(dev, predictions, known_record_ids=[r.record_id for r in records])
    assert results.counts.unexpected_predictions == 1
    assert heldout_id in predictions and results.counts.examples == len(dev)


def test_split_selection(records):
    assert len(select_split(records, "all")) == len(records)
    assert len(select_split(records, "dev")) + len(select_split(records, "heldout")) == len(records)
    with pytest.raises(ValueError):
        select_split(records, "test")


def test_evaluate_requires_records():
    with pytest.raises(EvaluationInputError):
        evaluate([], {})


# --- Runs, manifest and CLI --------------------------------------------------------------------


def test_run_requires_exactly_one_prediction_source(tmp_path):
    with pytest.raises(EvaluationInputError, match="exactly one"):
        run(DATASET)
    with pytest.raises(EvaluationInputError, match="exactly one"):
        run(DATASET, baseline="abstain", predictions_path=tmp_path / "p.jsonl")
    with pytest.raises(EvaluationInputError, match="unknown baseline"):
        run(DATASET, baseline="guess")


def test_run_records_provenance_and_does_not_touch_the_dataset(tmp_path, records):
    before = file_sha256(DATASET)
    predictions = write_jsonl(
        tmp_path / "p.jsonl",
        [
            dict(json.loads(oracle(r).model_dump_json()), model_id="model-x", prompt_version="v1")
            for r in records
        ],
    )
    report = run(DATASET, predictions_path=predictions, split="heldout")
    assert file_sha256(DATASET) == before
    assert report.manifest.dataset.sha256 == before
    assert report.manifest.dataset.records_evaluated == len(select_split(records, "heldout"))
    assert report.manifest.predictor.sha256 == file_sha256(predictions)
    assert report.manifest.predictor.model_ids == ["model-x"]
    assert report.manifest.predictor.prompt_versions == ["v1"]
    assert (
        report.manifest.dataset.human_reviewed.denominator
        == report.manifest.dataset.records_evaluated
    )
    assert report.manifest.environment.packages["rank_bm25"] != "not installed"
    assert report.results.counts.unexpected_predictions == 0


def test_runs_are_reproducible():
    first, second = run(DATASET, baseline="abstain"), run(DATASET, baseline="abstain")
    assert first.results == second.results


def test_report_round_trips_through_json():
    report = run(DATASET, baseline="abstain")
    assert EvalReport.model_validate_json(report.model_dump_json()) == report


def test_cli(tmp_path, capsys):
    out = tmp_path / "report.json"
    assert cli.main(["--dataset", str(DATASET), "--baseline", "abstain", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Verdict accuracy" in printed and "Confusion" in printed
    assert (
        json.loads(out.read_text(encoding="utf-8"))["manifest"]["predictor"]["name"]
        == "baseline-abstain"
    )


def test_cli_reports_input_errors(tmp_path, capsys):
    assert cli.main(["--dataset", str(tmp_path / "missing.jsonl"), "--baseline", "abstain"]) == 2
    assert "cannot read" in capsys.readouterr().err


# --- The engine as a predictor (scripted provider: tests plumbing, not quality) ----------------


def test_engine_predictor_runs_retrieval_verifier_and_guard(tmp_path, records):
    from inkloom_verify.providers.base import ProviderTimeoutError
    from inkloom_verify.providers.fake import ScriptedProvider

    calls = {"n": 0}

    def reply(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return ProviderTimeoutError("slow")
        return {"verdict": "NOT_ENOUGH_EVIDENCE", "citations": [], "rationale": "unsure"}

    provider = ScriptedProvider(*([reply] * 100))
    saved = tmp_path / "predictions.jsonl"
    report = run(DATASET, engine_provider=provider, split="heldout", save_predictions=saved)
    heldout = select_split(records, "heldout")
    assert report.manifest.predictor.kind == "engine"
    assert report.manifest.predictor.prompt_versions == ["verify-claim-v1"]
    assert report.results.counts.examples == len(heldout)
    # One model call per record with retrieved passages; records without passages never call it.
    assert len(provider.calls) == len(heldout) - round(
        report.results.retrieval.empty_results.numerator
    )
    assert report.results.counts.predicted[E] == 1  # the timeout is an ERROR, not a verdict
    predictions = load_predictions(saved)
    assert set(predictions) == {r.record_id for r in heldout}
    assert all(
        "expected_verdict" not in line for line in saved.read_text(encoding="utf-8").splitlines()
    )


def test_engine_requires_exactly_one_source():
    from inkloom_verify.providers.fake import ScriptedProvider

    with pytest.raises(EvaluationInputError, match="exactly one"):
        run(DATASET, baseline="abstain", engine_provider=ScriptedProvider())


def test_cli_verifier_without_configuration_fails_clearly(monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("INKLOOM_LLM_MODELS", raising=False)
    assert cli.main(["--dataset", str(DATASET), "--verifier", "openrouter"]) == 2
    err = capsys.readouterr().err
    assert "OPENROUTER_API_KEY" in err and "INKLOOM_LLM_MODELS" in err
