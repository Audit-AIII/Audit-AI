"""Evaluation of claim extraction over labelled paragraphs (eval/data/extraction_v1.jsonl).

Three questions, kept apart:

* **Does the code keep claims intact?** An oracle model answers exactly as labelled; the real
  extractor must return every labelled claim with its exact source span (``content[start:end] ==
  claim.text``) and nothing else. This tests offsets, sentence splitting and grounding on real
  text (accents, emoji, lists, abbreviations), not a model.
* **What does the code enforce against a misbehaving model?** Scripted adversaries embellish
  claims (new numbers, months, names, dropped negations), merge compound claims, or extract
  opinions. Embellishment must never survive into a claim's statement; merging and opinion
  leakage cannot be prevented by code, only measured, and the metrics must see them.
* **How good is a real model?** Only with credentials (run_eval.py --verdicts openrouter).

Matching: a predicted claim *covers* a labelled claim when it overlaps at least half of the
label's span. Claim recall = labels covered / labels; precision = predictions covering some label
/ predictions; an atomicity violation is a prediction covering two or more labels; opinion
leakage is a prediction inside a sentence labelled non-factual.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from inkloom_verify.evaluation.metrics import Ratio, ratio
from inkloom_verify.extraction import ClaimExtractor, ExtractionConfig, ExtractionResult
from inkloom_verify.providers.base import JsonCompletionRequest, LLMProvider
from inkloom_verify.providers.fake import ResponderProvider


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LabelledClaim(_Model):
    text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    statement: str | None = None  # the standalone wording, when it differs from the source words


class NonFactualSentence(_Model):
    text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    kind: str = Field(pattern="^(opinion|stylistic|other)$")


class ExtractionRecord(_Model):
    record_id: str = Field(pattern=r"^x-\d{3}$")
    split: str = Field(pattern="^(dev|heldout)$")
    text: str = Field(min_length=1)
    claims: list[LabelledClaim]
    non_factual: list[NonFactualSentence] = []
    categories: list[str] = Field(min_length=1)
    label_rationale: str = Field(min_length=1)
    reviewed_by: list[str] = []

    @model_validator(mode="after")
    def _check_offsets(self) -> ExtractionRecord:
        for item in [*self.claims, *self.non_factual]:
            if self.text[item.start : item.end] != item.text:
                raise ValueError(
                    f"{self.record_id}: {item.text!r} is not the text at [{item.start}, {item.end})"
                )
        return self


def load_extraction_records(path: Path) -> list[ExtractionRecord]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    records = [ExtractionRecord.model_validate_json(line) for line in lines]
    ids = [r.record_id for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate record_id in the extraction dataset")
    return records


# --- Scripted models ----------------------------------------------------------------------------

Responder = Callable[[JsonCompletionRequest], dict[str, Any]]


def _sentences(request: JsonCompletionRequest) -> list[dict[str, str]]:
    block = request.user.split("<content_json>\n", 1)[1].rsplit("\n</content_json>", 1)[0]
    return json.loads(block)["sentences"]


def _labelled_by_sentence(record: ExtractionRecord, request: JsonCompletionRequest):
    """(sentence id, sentence text, labelled claims inside it, non-factual kind or None)."""
    cursor = 0
    for sentence in _sentences(request):
        start = record.text.find(sentence["text"], cursor)
        end = start + len(sentence["text"])
        cursor = end if start >= 0 else cursor
        inside = [c for c in record.claims if start <= c.start and c.end <= end]
        kind = next((n.kind for n in record.non_factual if start <= n.start and n.end <= end), None)
        yield sentence["id"], sentence["text"], inside, kind


def oracle(record: ExtractionRecord) -> Responder:
    """Answers exactly as labelled."""

    def respond(request: JsonCompletionRequest) -> dict[str, Any]:
        statements = []
        for sid, _, inside, kind in _labelled_by_sentence(record, request):
            if inside:
                statements.append(
                    {
                        "sentence_id": sid,
                        "kind": "factual",
                        "claims": [
                            {"text": c.statement or c.text, "source_quote": c.text} for c in inside
                        ],
                    }
                )
            else:
                statements.append({"sentence_id": sid, "kind": kind or "other", "claims": []})
        return {"statements": statements}

    return respond


def _embellish(statement: str) -> str:
    """One unsupported change per claim: a different number, an added month, a dropped negation,
    or an invented name."""
    if re.search(r"\d", statement):
        return re.sub(r"\d+", lambda m: str(int(m.group(0)) + 1), statement, count=1)
    if re.search(r"\bnot\b", statement):
        return re.sub(r"\s*\bnot\b", "", statement, count=1)
    return statement.rstrip(".") + ", says Marta Costa, since June 2024."


def embellisher(record: ExtractionRecord) -> Responder:
    """Labels the right sentences but changes every claim's wording unsafely."""

    def respond(request: JsonCompletionRequest) -> dict[str, Any]:
        data = oracle(record)(request)
        for statement in data["statements"]:
            for claim in statement["claims"]:
                claim["text"] = _embellish(claim["text"])
        return data

    return respond


def merger(record: ExtractionRecord) -> Responder:
    """Returns one claim per factual sentence, merging compound claims (not atomic)."""

    def respond(request: JsonCompletionRequest) -> dict[str, Any]:
        statements = []
        for sid, text, inside, kind in _labelled_by_sentence(record, request):
            if inside:
                statements.append(
                    {
                        "sentence_id": sid,
                        "kind": "factual",
                        "claims": [{"text": text, "source_quote": text}],
                    }
                )
            else:
                statements.append({"sentence_id": sid, "kind": kind or "other", "claims": []})
        return {"statements": statements}

    return respond


def opinion_leaker(record: ExtractionRecord) -> Responder:
    """Also extracts every non-factual sentence as a factual claim."""

    def respond(request: JsonCompletionRequest) -> dict[str, Any]:
        statements = []
        for sid, text, inside, _ in _labelled_by_sentence(record, request):
            claims = [{"text": c.statement or c.text, "source_quote": c.text} for c in inside] or [
                {"text": text, "source_quote": text}
            ]
            statements.append({"sentence_id": sid, "kind": "factual", "claims": claims})
        return {"statements": statements}

    return respond


ADVERSARIES: dict[str, Callable[[ExtractionRecord], Responder]] = {
    "embellisher": embellisher,
    "merger": merger,
    "opinion_leaker": opinion_leaker,
}


# --- Metrics ------------------------------------------------------------------------------------


class ExtractionMetrics(_Model):
    records: int
    labelled_claims: int
    predicted_claims: int
    claim_recall: Ratio
    claim_precision: Ratio
    atomicity_violations: int  # predictions covering two or more labelled claims
    opinion_leakage: int  # predictions inside sentences labelled non-factual
    slice_violations: int  # claim.text != content[start:end]; the contract makes this impossible
    exact_span_matches: Ratio  # labels whose exact span was returned
    statements_changed_unsafely: (
        int  # adversary statements kept despite the embellishment (0 expected)
    )
    records_failed: int  # extraction returned an error


def _covers(start: int, end: int, label: LabelledClaim) -> bool:
    return min(end, label.end) - max(start, label.start) >= (label.end - label.start) / 2


def score(
    records: Sequence[ExtractionRecord],
    results: Sequence[ExtractionResult],
    embellished: Callable[[str], str] | None = None,
) -> ExtractionMetrics:
    covered = matching = exact = atomicity = leakage = slices = unsafe = failed = predicted = 0
    for record, result in zip(records, results, strict=True):
        failed += bool(result.errors)
        for claim in result.claims:
            predicted += 1
            span = claim.source_span
            slices += record.text[span.start : span.end] != claim.text
            hits = [label for label in record.claims if _covers(span.start, span.end, label)]
            matching += bool(hits)
            atomicity += len(hits) >= 2
            leakage += any(n.start <= span.start and span.end <= n.end for n in record.non_factual)
            if embellished is not None:
                unsafe += any(
                    claim.statement == embellished(label.statement or label.text)
                    for label in record.claims
                )
        for label in record.claims:
            spans = [(c.source_span.start, c.source_span.end) for c in result.claims]
            covered += any(_covers(s, e, label) for s, e in spans)
            exact += (label.start, label.end) in spans
    labelled = sum(len(r.claims) for r in records)
    return ExtractionMetrics(
        records=len(records),
        labelled_claims=labelled,
        predicted_claims=predicted,
        claim_recall=ratio(covered, labelled),
        claim_precision=ratio(matching, predicted),
        atomicity_violations=atomicity,
        opinion_leakage=leakage,
        slice_violations=slices,
        exact_span_matches=ratio(exact, labelled),
        statements_changed_unsafely=unsafe,
        records_failed=failed,
    )


def extract_all(
    records: Sequence[ExtractionRecord],
    provider_for: Callable[[ExtractionRecord], LLMProvider],
    config: ExtractionConfig | None = None,
) -> list[ExtractionResult]:
    return [ClaimExtractor(provider_for(r), config).extract(r.text) for r in records]


def evaluate_extraction(
    records: Sequence[ExtractionRecord],
    live: LLMProvider | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """The report section: oracle replay, adversaries, and the live model when one is given."""
    section: dict[str, Any] = {
        "oracle": score(
            records, extract_all(records, lambda r: ResponderProvider(oracle(r)))
        ).model_dump(mode="json"),
        "adversaries": {},
        "live": None,
        "human_reviewed": sum(1 for r in records if r.reviewed_by),
    }
    for name, make in ADVERSARIES.items():
        results = extract_all(records, lambda r, make=make: ResponderProvider(make(r)))
        section["adversaries"][name] = score(
            records, results, _embellish if name == "embellisher" else None
        ).model_dump(mode="json")
    if live is not None:
        config = ExtractionConfig(prompt_version=prompt_version) if prompt_version else None
        section["live"] = score(records, extract_all(records, lambda r: live, config)).model_dump(
            mode="json"
        )
    return section
