"""EVAL.md Phase 4: the eight required metrics. Deterministic: hand-constructed predictions and
outcomes (eval/fixtures/required_metrics/), whose expected values are worked out by hand below."""

import copy
import json
from pathlib import Path

import pytest

from inkloom_verify.evaluation import required_metrics as rm
from inkloom_verify.evaluation.pipeline_predictor import CaseOutcome
from inkloom_verify.evaluation.runner import EvalPrediction, PredictedCitation, PredictedSpan, load_predictions, load_records
from inkloom_verify.schemas import EvalRecord

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "eval" / "fixtures" / "required_metrics"
RECORDS = load_records(FIXTURE / "dataset.jsonl")
BY_ID = {r.record_id: r for r in RECORDS}
PREDICTIONS = load_predictions(FIXTURE / "predictions.jsonl")
CASES = {c.record_id: c for c in (CaseOutcome.model_validate_json(l) for l in (FIXTURE / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}


@pytest.fixture(scope="module")
def fixture_metrics():
    return rm.compute(RECORDS, PREDICTIONS, CASES)


def ratio(r):
    return None if r is None else (r.numerator, r.denominator)


# --- The fixture, worked out by hand ------------------------------------------------------------------
#   label C:  v1-027 -> C (TP)   v1-025 -> C (TP)   v1-020 -> NEE (FN)   v3-006 -> missing (FN)
#   label ¬C: v1-009 S -> C (FP) v1-001 S -> S (TN) v1-037 NEE -> S (TN) v3-019 NEE -> ERROR (TN)


def test_confusion_counts(fixture_metrics):
    c = fixture_metrics.counts
    assert (c["tp"], c["fp"], c["fn"], c["tn"]) == (2, 1, 2, 3)
    assert c["evaluated"] == 8 and c["missing_predictions"] == 1 and c["error_predictions"] == 2  # ERROR + the missing one


def test_classification_metrics(fixture_metrics):
    m = fixture_metrics
    assert ratio(m.contradicted_precision) == (2, 3)  # TP / (TP + FP)
    assert ratio(m.contradicted_recall) == (2, 4)     # TP / (TP + FN), the missing prediction is an FN
    assert ratio(m.false_positive_rate) == (1, 4)     # FP / (FP + TN)
    assert ratio(m.false_negative_rate) == (2, 4)     # FN / (TP + FN)
    assert m.false_negative_rate.value == pytest.approx(1 - m.contradicted_recall.value)


def test_citation_validity_needs_resolution_and_support(fixture_metrics):
    """5 citations: v1-027, v1-025, v1-001 resolve and support; v1-009 is off by one character;
    v1-037 resolves but its record has no supporting evidence (NOT_ENOUGH_EVIDENCE)."""
    m = fixture_metrics
    assert ratio(m.citation_validity) == (3, 5) and ratio(m.citation_resolution) == (4, 5)
    assert m.citation_failures["does_not_resolve:quote_mismatch"] == 1
    assert m.citation_failures["no_supporting_evidence_exists"] == 1


def test_retrieval_recall_at_5_uses_the_real_retriever(fixture_metrics):
    m = fixture_metrics
    assert ratio(m.retrieval_recall_at_5) == (6, 6)  # 6 records with gold evidence; 2 NOT_ENOUGH_EVIDENCE excluded
    assert m.retrieval["excluded_without_gold_evidence"] == 2 and m.retrieval["k"] == 5


def test_human_review_share_and_its_exclusions(fixture_metrics):
    m = fixture_metrics
    assert ratio(m.human_review_share) == (5, 7)  # v3-006 has no outcome: excluded, and counted
    assert m.review["excluded_without_outcome"] == 1 and m.review["auto_cleared"] == 2
    assert m.review["auto_cleared_but_not_supported"] == ["v1-037"]  # the safety number


def test_correction_traceability(fixture_metrics):
    m = fixture_metrics
    assert ratio(m.correction_traceability) == (1, 2)  # €99 -> €129 traceable; "microwave safe" is not
    assert m.corrections["untraceable"] == [{"record_id": "v1-025", "claim_id": "clm_0001", "reasons": ["unsupported:microwave"]}]
    assert m.corrections["attempts_by_status"] == {"proposed": 2, "needs_human_review": 1}
    assert m.corrections["claims_not_applicable"] == 4


def test_the_committed_sample_report_is_what_the_fixture_produces(fixture_metrics):
    committed = (FIXTURE / "SAMPLE_REPORT.md").read_text(encoding="utf-8")
    assert committed.startswith("# SAMPLE REPORT: TEST FIXTURE, NOT A MEASUREMENT")
    assert "No model was run" in committed
    assert committed.endswith(rm.markdown(fixture_metrics))


# --- Edge cases ---------------------------------------------------------------------------------------


def pred(record_id, verdict, *citations):
    return EvalPrediction(record_id=record_id, verdict=verdict,
                          citations=[PredictedCitation(doc_id=d, quote=q, quote_span=PredictedSpan(start=s, end=e), doc_text_sha256=h)
                                     for d, q, s, e, h in citations])


def gold_citation(record_id, **changes):
    g = BY_ID[record_id].gold_evidence[0]
    c = {"doc_id": g.doc_id, "quote": g.quote, "start": g.span.start, "end": g.span.end, "sha": None} | changes
    return (c["doc_id"], c["quote"], c["start"], c["end"], c["sha"])


def test_zero_denominators_are_unavailable_never_zero():
    supported_only = [BY_ID["v1-001"]]
    m = rm.compute(supported_only, {"v1-001": pred("v1-001", "SUPPORTED")})
    assert m.contradicted_recall is None and m.false_negative_rate is None and m.contradicted_precision is None
    assert m.citation_validity is None and m.citation_resolution is None
    assert m.human_review_share is None and m.correction_traceability is None
    assert set(m.unavailable) == {"contradicted_precision", "contradicted_recall", "false_negative_rate", "citation_validity",
                                  "citation_resolution", "human_review_share", "correction_traceability"}
    assert "never predicted" in m.unavailable["contradicted_precision"]
    assert "needs --pipeline full" in m.unavailable["human_review_share"]
    assert "unavailable (" in rm.markdown(m) and "0.0% (0/0)" not in rm.markdown(m)


def test_no_gold_evidence_makes_recall_at_5_unavailable():
    m = rm.compute([BY_ID["v1-037"], BY_ID["v3-019"]], {})
    assert m.retrieval_recall_at_5 is None and m.retrieval["excluded_without_gold_evidence"] == 2


def test_missing_predictions_are_errors_not_positives():
    m = rm.compute([BY_ID["v1-027"], BY_ID["v1-001"]], {})
    assert (m.counts["fn"], m.counts["tn"], m.counts["tp"], m.counts["fp"]) == (1, 1, 0, 0)
    assert m.counts["missing_predictions"] == 2 and m.counts["error_predictions"] == 2


def test_unexpected_predictions_are_counted_and_ignored():
    m = rm.compute([BY_ID["v1-027"]], {"v1-027": pred("v1-027", "CONTRADICTED", gold_citation("v1-027")),
                                       "nope-1": pred("nope-1", "CONTRADICTED")})
    assert m.counts["unexpected_predictions"] == 1 and ratio(m.contradicted_precision) == (1, 1)


def test_an_invalid_label_is_excluded_and_counted():
    broken = EvalRecord.model_construct(**{**BY_ID["v1-001"].__dict__, "expected_verdict": "ERROR"})
    m = rm.compute([broken, BY_ID["v1-027"]], {"v1-027": pred("v1-027", "CONTRADICTED", gold_citation("v1-027"))})
    assert m.counts["invalid_labels"] == 1 and m.counts["evaluated"] == 1


def test_failed_retrieval_is_a_miss():
    record = copy.deepcopy(BY_ID["v1-027"])
    record = record.model_copy(update={"claim_text": "Zyxw qvut."})  # shares no word with any reference
    m = rm.compute([record], {})
    assert ratio(m.retrieval_recall_at_5) == (0, 1) and m.retrieval["empty_results"] == 1
    assert m.retrieval["misses"] == ["v1-027"]


def test_a_definite_verdict_without_citation_is_reported_not_counted_valid():
    m = rm.compute([BY_ID["v1-027"]], {"v1-027": pred("v1-027", "CONTRADICTED")})
    assert m.citation_failures["definite_verdict_without_citation"] == 1 and m.citation_validity is None


@pytest.mark.parametrize(("record_id", "verdict", "citation", "failure"), [
    ("v1-027", "CONTRADICTED", gold_citation("v1-027", doc_id="invented-doc"), "does_not_resolve:unknown_document"),
    ("v1-027", "CONTRADICTED", gold_citation("v1-027", sha="0" * 64), "does_not_resolve:wrong_document_version"),
    ("v1-027", "CONTRADICTED", gold_citation("v1-027", quote="x"), "does_not_resolve:quote_mismatch"),  # a non-empty string is not evidence
    ("v1-027", "CONTRADICTED", gold_citation("v1-027", start=10_000, end=10_010), "does_not_resolve:span_out_of_range"),
    ("v1-027", "SUPPORTED", gold_citation("v1-027"), "supports_a_different_verdict"),
    ("v1-037", "SUPPORTED", None, "no_supporting_evidence_exists"),
    ("v1-027", "NOT_ENOUGH_EVIDENCE", gold_citation("v1-027"), "cited_on_abstention_or_error"),
], ids=["unknown-doc", "wrong-version", "bare-string", "out-of-range", "wrong-verdict", "no-evidence-exists", "on-abstention"])
def test_citations_that_do_not_resolve_or_do_not_support_are_invalid(record_id, verdict, citation, failure):
    if citation is None:
        text = BY_ID[record_id].references[0].text
        start = text.index("Charging: USB-C.")
        citation = (BY_ID[record_id].references[0].doc_id, "Charging: USB-C.", start, start + 16, None)
    m = rm.compute([BY_ID[record_id]], {record_id: pred(record_id, verdict, citation)})
    assert ratio(m.citation_validity) == (0, 1) and m.citation_failures[failure] == 1


def test_a_real_quote_that_is_not_the_annotated_evidence_is_not_supporting():
    record = BY_ID["v1-027"]
    text = record.references[0].text
    quote = "Warranty: 2 years."
    start = text.index(quote)
    m = rm.compute([record], {"v1-027": pred("v1-027", "CONTRADICTED", (record.references[0].doc_id, quote, start, start + len(quote), None))})
    assert ratio(m.citation_resolution) == (1, 1) and ratio(m.citation_validity) == (0, 1)
    assert m.citation_failures["not_the_annotated_evidence"] == 1


# --- Correction traceability, one rule at a time --------------------------------------------------------


PRICE = {"doc_id": "pods-fact-sheet", "quote": "Price: €129 (EU launch price).",
         "start": BY_ID["v1-027"].gold_evidence[0].span.start, "end": BY_ID["v1-027"].gold_evidence[0].span.end}


@pytest.mark.parametrize(("correction", "claim_citations", "expected"), [
    ({"replacement_text": "€129", "citations": [PRICE]}, [PRICE], []),
    ({"replacement_text": "€129", "citations": []}, [PRICE], ["no_citation", "unsupported:129"]),  # nothing permitted supports 129
    ({"replacement_text": "€129", "citations": [PRICE | {"quote": "Price: €1"}]}, [PRICE], ["citation_not_in_references", "unsupported:129"]),
    ({"replacement_text": "€129", "citations": [PRICE]}, [], ["citation_not_among_claim_evidence", "unsupported:129"]),
    ({"replacement_text": "€119", "citations": [PRICE]}, [PRICE], ["unsupported:119"]),
    ({"replacement_text": "€129 only today", "citations": [PRICE]}, [PRICE], ["unsupported:only", "unsupported:today"]),
    ({"replacement_text": "a hundred and twenty-nine euros", "citations": [PRICE]}, [PRICE],
     ["unsupported:a", "unsupported:hundred", "unsupported:and", "unsupported:twenty", "unsupported:nine", "unsupported:euros"]),
    ({"replacement_text": " ", "citations": [PRICE]}, [PRICE], ["empty_replacement"]),
], ids=["traceable", "no-citation", "citation-not-in-references", "not-permitted-evidence", "wrong-number", "added-words",
        "same-meaning-other-words", "empty"])
def test_traceability_rules(correction, claim_citations, expected):
    """'a hundred and twenty-nine euros' means €129, but the check is lexical: equivalence that is
    not in the evidence's own words is not treated as proven."""
    assert rm.traceability_problems(BY_ID["v1-027"], claim_citations, correction, "€99") == expected


def test_corrections_not_applicable_leave_traceability_unavailable():
    outcomes = {k: v for k, v in CASES.items() if k in ("v1-001", "v1-020")}  # no correction attempts at all
    m = rm.compute([BY_ID["v1-001"], BY_ID["v1-020"]], {}, outcomes)
    assert m.correction_traceability is None and m.unavailable["correction_traceability"] == "no correction was proposed"
    assert m.corrections["claims_not_applicable"] == 2 and ratio(m.human_review_share) == (1, 2)


# --- The runner reports them --------------------------------------------------------------------------


def test_the_default_run_reports_the_metrics_it_can_measure(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_eval_p4", ROOT / "eval" / "run_eval.py")
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)
    assert run_eval.main(["--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    m = report["required_metrics"]
    assert m["counts"]["evaluated"] == 80 and m["contradicted_recall"]["denominator"] == 32
    assert m["retrieval_recall_at_5"]["denominator"] == 57
    assert {"contradicted_precision", "citation_validity", "human_review_share", "correction_traceability"} <= set(m["unavailable"])
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "## 11. Required metrics" in text and "not model quality" in text
