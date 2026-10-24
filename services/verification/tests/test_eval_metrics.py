import pytest

from inkloom_verify.evaluation import metrics
from inkloom_verify.evaluation.metrics import CitationProblem
from inkloom_verify.schemas import EvalRecord, SourceSpan, Verdict

S, C, N, E = Verdict.SUPPORTED, Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE, Verdict.ERROR

# 11 examples with hand-computed metrics (see test_hand_computed_*).
PAIRS = [(S, S)] * 3 + [(S, N)] + [(C, C)] * 2 + [(C, S)] + [(N, N)] * 2 + [(N, C)] + [(N, E)]


@pytest.fixture
def confusion():
    return metrics.confusion_matrix(PAIRS)


def test_ratio():
    assert metrics.ratio(1, 4).value == 0.25
    assert str(metrics.ratio(1, 4)) == "25.0% (1/4)"
    assert metrics.ratio(0, 0).value is None
    assert str(metrics.ratio(0, 0)) == "n/a (0/0)"
    for bad in [(-1, 2), (3, 2), (0, -1)]:
        with pytest.raises(ValueError):
            metrics.ratio(*bad)


def test_confusion_matrix_has_every_cell(confusion):
    assert set(confusion) == {S, C, N}
    assert all(set(row) == {S, C, N, E} for row in confusion.values())
    assert confusion[S] == {S: 3, C: 0, N: 1, E: 0}
    assert confusion[N] == {S: 0, C: 1, N: 2, E: 1}


def test_error_is_not_a_gold_class():
    with pytest.raises(ValueError, match="not a gold class"):
        metrics.confusion_matrix([(E, S)])


def test_hand_computed_accuracy_and_rates(confusion):
    assert metrics.accuracy(confusion) == metrics.ratio(7, 11)
    assert metrics.predicted_rate(confusion, N) == metrics.ratio(3, 11)  # abstention
    assert metrics.predicted_rate(confusion, E) == metrics.ratio(1, 11)
    assert metrics.false_supported_rate(confusion) == metrics.ratio(1, 7)
    assert metrics.catch_rate(confusion) == metrics.ratio(5, 7)
    assert metrics.false_positive_rate(confusion) == metrics.ratio(1, 4)


def test_hand_computed_per_class(confusion):
    s = metrics.class_metrics(confusion, S)
    assert (s.support, s.predicted, s.precision, s.recall) == (
        4,
        4,
        metrics.ratio(3, 4),
        metrics.ratio(3, 4),
    )
    assert s.f1 == pytest.approx(0.75)
    c = metrics.class_metrics(confusion, C)
    assert (c.precision, c.recall) == (metrics.ratio(2, 3), metrics.ratio(2, 3))
    assert c.f1 == pytest.approx(2 / 3)
    n = metrics.class_metrics(confusion, N)
    assert (n.precision, n.recall) == (metrics.ratio(2, 3), metrics.ratio(2, 4))
    assert n.f1 == pytest.approx(4 / 7)
    per_class = {cls: metrics.class_metrics(confusion, cls) for cls in (S, C, N)}
    macro = metrics.macro_f1(per_class)
    assert macro.value == pytest.approx((0.75 + 2 / 3 + 4 / 7) / 3)
    assert macro.classes == [S, C, N]


def test_class_without_examples_is_undefined_and_left_out_of_macro_f1():
    confusion = metrics.confusion_matrix([(S, S), (N, N), (N, S)])
    contradicted = metrics.class_metrics(confusion, C)
    assert contradicted.support == 0
    assert contradicted.recall.value is None and contradicted.precision.value is None
    assert contradicted.f1 is None
    per_class = {cls: metrics.class_metrics(confusion, cls) for cls in (S, C, N)}
    assert metrics.macro_f1(per_class).classes == [S, N]


def test_class_never_predicted_scores_zero_f1_not_undefined():
    confusion = metrics.confusion_matrix([(S, N), (N, N)])
    supported = metrics.class_metrics(confusion, S)
    assert supported.precision.value is None
    assert supported.recall == metrics.ratio(0, 1)
    assert supported.f1 == 0.0


def test_empty_evaluation_has_no_percentages():
    confusion = metrics.confusion_matrix([])
    assert metrics.accuracy(confusion).value is None
    assert metrics.false_supported_rate(confusion).value is None
    assert metrics.catch_rate(confusion).value is None
    per_class = {cls: metrics.class_metrics(confusion, cls) for cls in (S, C, N)}
    assert metrics.macro_f1(per_class).value is None


def test_rates_without_their_population_are_undefined():
    only_supported = metrics.confusion_matrix([(S, S), (S, N)])
    assert metrics.false_supported_rate(only_supported).value is None
    assert metrics.catch_rate(only_supported).value is None
    assert metrics.false_positive_rate(only_supported) == metrics.ratio(1, 2)


# --- Citations ---------------------------------------------------------------------------------

DOC_TEXT = "Weight: 5.2 g per earbud. Price: 129 EUR."


@pytest.fixture
def record() -> EvalRecord:
    return EvalRecord(
        record_id="r1",
        claim_text="Each earbud weighs 5.2 g.",
        references=[
            {"doc_id": "sheet", "text": DOC_TEXT},
            {"doc_id": "other", "text": "Unrelated."},
        ],
        expected_verdict="SUPPORTED",
        gold_evidence=[
            {"doc_id": "sheet", "span": {"start": 0, "end": 24}, "quote": DOC_TEXT[:24]}
        ],
        label_rationale="Stated in the sheet.",
    )


def test_valid_citation(record):
    assert metrics.citation_problem(record, "sheet", "5.2 g per earbud", 8, 24) is None
    sha = record.references[0].text_sha256
    assert metrics.citation_problem(record, "sheet", "5.2 g per earbud", 8, 24, sha) is None


@pytest.mark.parametrize(
    ("doc_id", "quote", "start", "end", "sha", "problem"),
    [
        ("missing", "5.2 g", 8, 13, None, CitationProblem.UNKNOWN_DOCUMENT),
        ("sheet", "5.2 g", 8, 13, "0" * 64, CitationProblem.WRONG_DOCUMENT_VERSION),
        ("sheet", "  ", 8, 10, None, CitationProblem.BLANK_QUOTE),
        ("sheet", "5.2 g", 13, 8, None, CitationProblem.SPAN_OUT_OF_RANGE),
        ("sheet", "5.2 g", 8, 8, None, CitationProblem.SPAN_OUT_OF_RANGE),
        ("sheet", "5.2 g", -1, 4, None, CitationProblem.SPAN_OUT_OF_RANGE),
        ("sheet", "EUR.x", 37, 42, None, CitationProblem.SPAN_OUT_OF_RANGE),
        ("sheet", "6.2 g", 8, 13, None, CitationProblem.QUOTE_MISMATCH),
        ("sheet", "5.2 g", 9, 14, None, CitationProblem.QUOTE_MISMATCH),
    ],
)
def test_citation_problems(record, doc_id, quote, start, end, sha, problem):
    assert metrics.citation_problem(record, doc_id, quote, start, end, sha) is problem


def test_overlap_with_gold(record):
    assert metrics.overlaps_gold(record, "sheet", 8, 13)
    assert metrics.overlaps_gold(record, "sheet", 23, 30)
    assert not metrics.overlaps_gold(record, "sheet", 24, 30)  # adjacent, not overlapping
    assert not metrics.overlaps_gold(record, "other", 0, 5)


def test_gold_spans_covered(record):
    assert metrics.gold_spans_covered(record, [("sheet", SourceSpan(start=20, end=30))]) == 1
    assert metrics.gold_spans_covered(record, [("other", SourceSpan(start=0, end=5))]) == 0
    assert metrics.gold_spans_covered(record, []) == 0
