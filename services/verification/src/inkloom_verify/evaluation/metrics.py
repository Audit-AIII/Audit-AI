"""Metric calculations for the claim-verification evaluation.

Pure functions over labels and predictions. Every rate is a ``Ratio`` that carries its numerator
and denominator; a rate with a zero denominator has ``value=None`` and is reported as "n/a",
never as 0% or 100%.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from enum import Enum

from pydantic import BaseModel, ConfigDict

from inkloom_verify.schemas import EvalRecord, SourceSpan, Verdict

# The verdicts a label can take. ERROR is an engine outcome only and never a gold class.
GOLD_CLASSES: tuple[Verdict, ...] = (
    Verdict.SUPPORTED,
    Verdict.CONTRADICTED,
    Verdict.NOT_ENOUGH_EVIDENCE,
)
PREDICTED_CLASSES: tuple[Verdict, ...] = (*GOLD_CLASSES, Verdict.ERROR)
DEFINITE: frozenset[Verdict] = frozenset({Verdict.SUPPORTED, Verdict.CONTRADICTED})


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Ratio(_Model):
    numerator: int
    denominator: int
    value: float | None

    def __str__(self) -> str:
        if self.value is None:
            return f"n/a ({self.numerator}/{self.denominator})"
        return f"{self.value:.1%} ({self.numerator}/{self.denominator})"


def ratio(numerator: int, denominator: int) -> Ratio:
    if numerator < 0 or denominator < 0 or numerator > denominator:
        raise ValueError(f"invalid ratio {numerator}/{denominator}")
    return Ratio(
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
    )


class ClassMetrics(_Model):
    """Precision, recall and F1 for one gold class.

    * precision = correct predictions of the class / all predictions of the class
      (n/a when the class was never predicted)
    * recall = correct predictions of the class / gold examples of the class
      (n/a when the class has no gold examples)
    * f1 = harmonic mean. n/a when recall is n/a. When the class has gold examples but was
      never predicted, recall is 0 and f1 is 0: missing a class entirely is a failure, not an
      undefined result.
    """

    support: int
    predicted: int
    precision: Ratio
    recall: Ratio
    f1: float | None


Confusion = dict[Verdict, dict[Verdict, int]]


def confusion_matrix(pairs: Iterable[tuple[Verdict, Verdict]]) -> Confusion:
    """Rows are gold classes, columns are predicted classes (ERROR included), all cells present."""
    counts = Counter(pairs)
    for gold, _ in counts:
        if gold not in GOLD_CLASSES:
            raise ValueError(f"{gold.value} is not a gold class")
    return {
        gold: {pred: counts.get((gold, pred), 0) for pred in PREDICTED_CLASSES}
        for gold in GOLD_CLASSES
    }


def class_metrics(confusion: Confusion, cls: Verdict) -> ClassMetrics:
    support = sum(confusion[cls].values())
    predicted = sum(confusion[gold][cls] for gold in GOLD_CLASSES)
    correct = confusion[cls][cls]
    precision = ratio(correct, predicted)
    recall = ratio(correct, support)
    if recall.value is None:
        f1 = None
    elif precision.value is None or precision.value + recall.value == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision.value * recall.value / (precision.value + recall.value)
    return ClassMetrics(
        support=support, predicted=predicted, precision=precision, recall=recall, f1=f1
    )


class MacroF1(_Model):
    """Unweighted mean F1 over the gold classes that have at least one example."""

    value: float | None
    classes: list[Verdict]


def macro_f1(per_class: dict[Verdict, ClassMetrics]) -> MacroF1:
    included = [cls for cls in GOLD_CLASSES if per_class[cls].f1 is not None]
    if not included:
        return MacroF1(value=None, classes=[])
    return MacroF1(value=sum(per_class[c].f1 for c in included) / len(included), classes=included)  # type: ignore[misc]


def accuracy(confusion: Confusion) -> Ratio:
    total = sum(sum(row.values()) for row in confusion.values())
    return ratio(sum(confusion[c][c] for c in GOLD_CLASSES), total)


def predicted_rate(confusion: Confusion, cls: Verdict) -> Ratio:
    """Share of all examples predicted as ``cls``; denominator is every example."""
    total = sum(sum(row.values()) for row in confusion.values())
    return ratio(sum(confusion[gold][cls] for gold in GOLD_CLASSES), total)


def false_supported_rate(confusion: Confusion) -> Ratio:
    """SUPPORTED predictions on claims whose label is not SUPPORTED / those claims.

    The most harmful error: it tells a reviewer something is backed by the sources when it is not.
    """
    negatives = [Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE]
    return ratio(
        sum(confusion[g][Verdict.SUPPORTED] for g in negatives),
        sum(sum(confusion[g].values()) for g in negatives),
    )


# Trust Scorecard candidates. A claim is "flagged" when the engine would show it to a reviewer as
# a problem: CONTRADICTED or NOT_ENOUGH_EVIDENCE ("unverified"). ERROR is neither flagged nor
# cleared and is reported separately. These definitions are not yet agreed with the frontend.
FLAGGED: frozenset[Verdict] = frozenset({Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE})


def catch_rate(confusion: Confusion) -> Ratio:
    """Flagged predictions on claims labelled CONTRADICTED or NOT_ENOUGH_EVIDENCE / those claims."""
    issues = [Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE]
    caught = sum(confusion[g][p] for g in issues for p in FLAGGED)
    return ratio(caught, sum(sum(confusion[g].values()) for g in issues))


def false_positive_rate(confusion: Confusion) -> Ratio:
    """Flagged predictions on claims labelled SUPPORTED / claims labelled SUPPORTED."""
    row = confusion[Verdict.SUPPORTED]
    return ratio(sum(row[p] for p in FLAGGED), sum(row.values()))


# --- Citations ---------------------------------------------------------------------------------


class CitationProblem(str, Enum):
    UNKNOWN_DOCUMENT = "unknown_document"  # doc_id is not among the record's references
    WRONG_DOCUMENT_VERSION = "wrong_document_version"  # doc_text_sha256 given and different
    SPAN_OUT_OF_RANGE = (
        "span_out_of_range"  # span is empty, reversed or past the end of the document
    )
    QUOTE_MISMATCH = "quote_mismatch"  # the text at the span is not the quote
    BLANK_QUOTE = "blank_quote"


def citation_problem(
    record: EvalRecord,
    doc_id: str,
    quote: str,
    start: int,
    end: int,
    doc_text_sha256: str | None = None,
) -> CitationProblem | None:
    """Why a citation does not quote the record's references verbatim, or None if it does.

    This checks the quotation only. A valid citation can still support the wrong verdict.
    """
    documents = {d.doc_id: d for d in record.references}
    document = documents.get(doc_id)
    if document is None:
        return CitationProblem.UNKNOWN_DOCUMENT
    if doc_text_sha256 is not None and doc_text_sha256 != document.text_sha256:
        return CitationProblem.WRONG_DOCUMENT_VERSION
    if not quote.strip():
        return CitationProblem.BLANK_QUOTE
    if not 0 <= start < end <= len(document.text):
        return CitationProblem.SPAN_OUT_OF_RANGE
    if document.text[start:end] != quote:
        return CitationProblem.QUOTE_MISMATCH
    return None


def overlaps_gold(record: EvalRecord, doc_id: str, start: int, end: int) -> bool:
    """True when [start, end) in ``doc_id`` shares at least one character with a gold evidence span."""
    return any(
        g.doc_id == doc_id and start < g.span.end and g.span.start < end
        for g in record.gold_evidence
    )


def gold_spans_covered(record: EvalRecord, spans: Iterable[tuple[str, SourceSpan]]) -> int:
    """How many of the record's gold evidence spans overlap at least one of ``spans``."""
    spans = list(spans)
    return sum(
        1
        for g in record.gold_evidence
        if any(
            doc_id == g.doc_id and s.start < g.span.end and g.span.start < s.end
            for doc_id, s in spans
        )
    )
