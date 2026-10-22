"""Correction evaluation: labelled correction cases, checker measurement and live scoring.

Two measurements:

* ``check_candidates`` runs the deterministic correction checks on hand-labelled candidate edits.
  No model is involved, so it can run anywhere. It measures the checker, not the model.
* ``run_live`` asks the engine (model + checks + re-check) to correct each case, starting from a
  CONTRADICTED result built from the gold evidence, and scores the outcomes against the labels.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from inkloom_verify.chunking import ChunkingConfig, chunk_document
from inkloom_verify.evaluation.metrics import Ratio, ratio
from inkloom_verify.providers.base import ProviderError
from inkloom_verify.schemas import (
    Citation,
    ClaimText,
    ClaimResult,
    EvalSplit,
    EvidencePassage,
    GoldEvidence,
    InputContent,
    Label,
    RecordId,
    ReferenceDocument,
    SourceSpan,
    Verdict,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorrectionCandidate(_Model):
    """One possible edit and whether a correct checker should let it through."""

    original_text: ClaimText  # exact substring of the case's sentence
    replacement_text: str
    expected: Literal["accept", "reject"]
    note: Annotated[str, Field(min_length=1, max_length=300)]


class CorrectionCase(_Model):
    case_id: RecordId
    source_record_id: RecordId | None = None  # the verification record this case comes from
    split: EvalSplit = EvalSplit.DEV
    sentence: ClaimText  # the author's text, which is also the claim
    references: Annotated[list[ReferenceDocument], Field(min_length=1)]
    evidence: Annotated[list[GoldEvidence], Field(min_length=1)]  # the quotes that contradict it
    expected_outcome: Literal["correctable", "needs_human_review"]
    reference_corrections: list[ClaimText] = []  # acceptable corrected sentences
    candidates: list[CorrectionCandidate] = []
    rationale: ClaimText
    reviewed_by: Label | None = None

    @model_validator(mode="after")
    def _check(self) -> CorrectionCase:
        if (self.expected_outcome == "correctable") != bool(self.reference_corrections):
            raise ValueError("correctable cases need reference_corrections; others must have none")
        documents = {d.doc_id: d for d in self.references}
        for gold in self.evidence:
            document = documents.get(gold.doc_id)
            if document is None or gold.span.slice(document.text) != gold.quote:
                raise ValueError(f"evidence quote does not match {gold.doc_id}")
        for candidate in self.candidates:
            if candidate.original_text not in self.sentence:
                raise ValueError(f"candidate original_text not in sentence: {candidate.original_text!r}")
        return self


def load_cases(path: Path) -> list[CorrectionCase]:
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(CorrectionCase.model_validate_json(line))
        except ValidationError as error:
            first = error.errors()[0]
            raise ValueError(f"{path}:{number}: {'.'.join(map(str, first['loc']))}: {first['msg']}") from None
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError(f"{path}: duplicate case_id")
    return cases


# --- Checker measurement (no model) ------------------------------------------------------------


class CandidateOutcome(_Model):
    case_id: str
    original_text: str
    replacement_text: str
    expected: Literal["accept", "reject"]
    accepted: bool
    issues: list[str]
    note: str


class CheckerReport(_Model):
    candidates: int
    expected_accept: int
    expected_reject: int
    correctly_accepted: Ratio  # / candidates labelled accept
    correctly_rejected: Ratio  # / candidates labelled reject
    false_accepts: list[CandidateOutcome]  # labelled reject, let through: the dangerous error
    false_rejects: list[CandidateOutcome]  # labelled accept, blocked: costs a good fix
    rejection_codes: dict[str, int]


def check_candidates(cases: Sequence[CorrectionCase]) -> CheckerReport:
    from inkloom_verify.correction import correction_issues

    outcomes = []
    for case in cases:
        quotes = [g.quote for g in case.evidence]
        for candidate in case.candidates:
            issues = correction_issues(candidate.original_text, candidate.replacement_text, quotes)
            outcomes.append(
                CandidateOutcome(
                    case_id=case.case_id,
                    original_text=candidate.original_text,
                    replacement_text=candidate.replacement_text,
                    expected=candidate.expected,
                    accepted=not issues,
                    issues=[i.code.value for i in issues],
                    note=candidate.note,
                )
            )
    accept = [o for o in outcomes if o.expected == "accept"]
    reject = [o for o in outcomes if o.expected == "reject"]
    return CheckerReport(
        candidates=len(outcomes),
        expected_accept=len(accept),
        expected_reject=len(reject),
        correctly_accepted=ratio(sum(o.accepted for o in accept), len(accept)),
        correctly_rejected=ratio(sum(not o.accepted for o in reject), len(reject)),
        false_accepts=[o for o in reject if o.accepted],
        false_rejects=[o for o in accept if not o.accepted],
        rejection_codes=dict(sorted(Counter(code for o in outcomes for code in o.issues).items())),
    )


# --- Live engine measurement -------------------------------------------------------------------


def contradicted_result(case: CorrectionCase) -> tuple[ClaimResult, InputContent]:
    """A CONTRADICTED result citing the gold evidence, as if verification had produced it."""
    content = InputContent(text=case.sentence)
    passages: dict[str, EvidencePassage] = {}
    citations = []
    for order, document in enumerate(case.references):
        for p in chunk_document(document, ChunkingConfig(), doc_order=order):
            for gold in case.evidence:
                if p.doc_id == gold.doc_id and p.span.contains(gold.span) and p.passage_id not in passages:
                    passages[p.passage_id] = EvidencePassage(
                        passage_id=p.passage_id, doc_id=p.doc_id, doc_text_sha256=p.doc_text_sha256,
                        span=p.span, text=p.text, retrieval={"method": "bm25", "score": 1.0, "rank": len(passages) + 1},
                    )
    for gold in case.evidence:
        passage = next(p for p in passages.values() if p.doc_id == gold.doc_id and p.span.contains(gold.span))
        citations.append(
            Citation(doc_id=gold.doc_id, doc_text_sha256=passage.doc_text_sha256, passage_id=passage.passage_id,
                     quote=gold.quote, quote_span=gold.span)
        )
    result = ClaimResult(
        claim={"claim_id": "clm_0001", "text": case.sentence, "source_span": SourceSpan(start=0, end=len(case.sentence))},
        verdict=Verdict.CONTRADICTED,
        evidence=list(passages.values()),
        citations=citations,
    )
    return result, content


class LiveCaseOutcome(_Model):
    case_id: str
    expected_outcome: str
    status: str
    corrected_sentence: str | None
    matches_reference: bool
    word_edits: int | None
    issues: list[str]


class LiveReport(_Model):
    cases: int
    proposed_when_correctable: Ratio  # / correctable cases
    declined_when_needs_review: Ratio  # / needs-review cases (not PROPOSED)
    reference_match: Ratio  # proposals equal (whitespace-normalised) to a reference / proposals
    failed: int
    mean_word_edits: float | None
    outcomes: list[LiveCaseOutcome]


def run_live(cases: Sequence[CorrectionCase], provider) -> LiveReport:
    from inkloom_verify.correction import ClaimCorrector, edit_distance, words
    from inkloom_verify.schemas import CorrectionStatus
    from inkloom_verify.verification import ClaimVerifier

    outcomes = []
    for case in cases:
        result, content = contradicted_result(case)
        corrector = ClaimCorrector(provider, ClaimVerifier(provider, case.references))
        attempt_result = corrector.correct(result, content)
        attempt = attempt_result.correction_attempt
        assert attempt is not None
        corrected, edits = None, None
        if attempt_result.correction is not None:
            c = attempt_result.correction
            corrected = case.sentence[: c.target_span.start] + c.replacement_text + case.sentence[c.target_span.end :]
            edits = edit_distance(words(c.original_text), words(c.replacement_text))
        normalized = " ".join(corrected.split()) if corrected else None
        outcomes.append(
            LiveCaseOutcome(
                case_id=case.case_id,
                expected_outcome=case.expected_outcome,
                status=attempt.status.value,
                corrected_sentence=corrected,
                matches_reference=normalized is not None and normalized in {" ".join(r.split()) for r in case.reference_corrections},
                word_edits=edits,
                issues=[i.code.value for i in attempt.issues] + ([attempt.error.code.value] if attempt.error else []),
            )
        )
    correctable = [o for o in outcomes if o.expected_outcome == "correctable"]
    review = [o for o in outcomes if o.expected_outcome == "needs_human_review"]
    proposals = [o for o in outcomes if o.status == CorrectionStatus.PROPOSED.value]
    edits = [o.word_edits for o in proposals if o.word_edits is not None]
    return LiveReport(
        cases=len(outcomes),
        proposed_when_correctable=ratio(sum(o.status == "proposed" for o in correctable), len(correctable)),
        declined_when_needs_review=ratio(sum(o.status != "proposed" for o in review), len(review)),
        reference_match=ratio(sum(o.matches_reference for o in proposals), len(proposals)),
        failed=sum(o.status == CorrectionStatus.FAILED.value for o in outcomes),
        mean_word_edits=sum(edits) / len(edits) if edits else None,
        outcomes=outcomes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m inkloom_verify.evaluation.corrections")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--verifier", choices=["openrouter"], help="also run the engine live on every case")
    parser.add_argument("--out", type=Path, help="write the JSON report here")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.cases)
        report: dict = {"checker": check_candidates(cases).model_dump(mode="json")}
        if args.verifier == "openrouter":
            from inkloom_verify.providers.openrouter import OpenRouterProvider

            report["live"] = run_live(cases, OpenRouterProvider.from_env()).model_dump(mode="json")
    except (ValueError, OSError, ProviderError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    checker = report["checker"]
    print(f"Candidates {checker['candidates']} ({checker['expected_accept']} good, {checker['expected_reject']} bad)")
    for key in ("correctly_accepted", "correctly_rejected"):
        r = checker[key]
        value = "n/a" if r["value"] is None else f"{r['value']:.1%}"
        print(f"  {key:<20} {value} ({r['numerator']}/{r['denominator']})")
    for key in ("false_accepts", "false_rejects"):
        print(f"  {key}: {len(checker[key])}")
        for o in checker[key]:
            print(f"    {o['case_id']}: {o['original_text']!r} -> {o['replacement_text']!r}  [{o['note']}]")
    print(f"  rejection codes: {checker['rejection_codes']}")
    if "live" in report:
        print(json.dumps({k: v for k, v in report["live"].items() if k != "outcomes"}, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
