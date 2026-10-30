"""Validates a claim-verification dataset (JSONL of ``EvalRecord``) and summarises it.

``python -m inkloom_verify.evaluation.dataset eval/dataset.jsonl`` prints the class distribution
and coverage, and exits 1 if any problem is found (2 if the file cannot be read).

``EvalRecord`` already enforces each record on its own: required fields, a valid label (never
ERROR), gold evidence present exactly for SUPPORTED and CONTRADICTED, each gold quote equal to the
document text at its span, and document hashes. This module adds what needs the whole file, and
reports every problem rather than stopping at the first:

* every line is one JSON object; record ids are unique;
* a ``doc_id`` has the same text (and version) in every record that uses it;
* no gold quote comes from a sentence that gives instructions (``security.instruction_like``):
  instructions are never evidence;
* every ``prompt_injection`` record actually contains an injection, in the content
  (``injection_in_content``) or in a reference (``injection_in_reference``), and its tag agrees;
* required hard-case categories are covered, and the class mix is reported against EVAL.md's
  targets (30% SUPPORTED, 35% CONTRADICTED, 25% NOT_ENOUGH_EVIDENCE, 10% adversarial).

**Adversarial is not a label.** An adversarial record (category ``prompt_injection``) still has
one of the three labels, judged on its facts alone. The four target shares therefore count the
non-adversarial records per label, plus the adversarial records as a fourth group.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from inkloom_verify.chunking import sentence_spans
from inkloom_verify.schemas import MAX_PASSAGE_CHARS, EvalCategory, EvalRecord, Verdict
from inkloom_verify.security import instruction_like

TARGET_SHARES = {
    "SUPPORTED": 0.30,
    "CONTRADICTED": 0.35,
    "NOT_ENOUGH_EVIDENCE": 0.25,
    "adversarial": 0.10,
}
SHARE_TOLERANCE = 0.05  # "approximately": each group within 5 points of its target
SIZE_RANGE = (50, 150)  # Round 3: raised from 100 so held-out can reach ~15 SUPPORTED records
INJECTION_TAGS = {"injection_in_content", "injection_in_reference"}

# Hard cases EVAL.md requires, each as a predicate over the records.
REQUIRED_COVERAGE = {
    "near-miss numbers": lambda r: EvalCategory.NEAR_MISS in r.categories,
    "negation": lambda r: EvalCategory.NEGATION in r.categories,
    "dates": lambda r: EvalCategory.DATE in r.categories
    and r.expected_verdict is Verdict.CONTRADICTED,
    "outdated facts": lambda r: EvalCategory.OUTDATED_FACT in r.categories,
    "unit mismatches": lambda r: EvalCategory.UNIT_MISMATCH in r.categories,
    "unsupported claims (missing evidence)": lambda r: EvalCategory.ABSENT_FACT in r.categories
    and r.expected_verdict is Verdict.NOT_ENOUGH_EVIDENCE,
    "compound claims, one part wrong": lambda r: EvalCategory.COMPOUND in r.categories
    and r.expected_verdict is Verdict.CONTRADICTED,
    "conflicting references": lambda r: EvalCategory.CONFLICTING_EVIDENCE in r.categories,
    "injection in submitted content": lambda r: injection_location(r) == "injection_in_content",
    "injection in a reference": lambda r: injection_location(r) == "injection_in_reference",
}


class DatasetReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    records: int
    problems: list[str]
    labels: dict[str, int]
    adversarial: int
    groups: dict[str, int]  # non-adversarial per label, plus "adversarial"
    shares: dict[str, float]
    splits: dict[str, int]
    categories: dict[str, int]
    coverage: dict[str, int]
    injection_locations: dict[str, int]
    human_reviewed: int

    @property
    def ok(self) -> bool:
        return not self.problems


def injection_location(record: EvalRecord) -> str | None:
    """Where a record's injection is: in the claim itself, or in one of its references."""
    if instruction_like(record.claim_text):
        return "injection_in_content"
    if any(
        instruction_like(d.text[s.start : s.end])
        for d in record.references
        for s in sentence_spans(d.text, MAX_PASSAGE_CHARS)
    ):
        return "injection_in_reference"
    return None


def _lines(path: Path) -> Iterable[tuple[int, str]]:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            yield number, line


def _first_error(error: ValidationError) -> str:
    first = error.errors(include_input=False, include_url=False)[0]
    return f"{'.'.join(str(p) for p in first['loc']) or 'record'}: {first['msg']}"


def validate_dataset(path: Path, *, check_mix: bool = True) -> DatasetReport:
    """Every problem in the file, plus its distribution. Raises OSError if it can't be read."""
    problems: list[str] = []
    records: list[EvalRecord] = []
    ids: dict[str, int] = {}
    for number, line in _lines(path):
        try:
            value: Any = json.loads(line)
        except json.JSONDecodeError as error:
            problems.append(f"line {number}: not valid JSON ({error.msg})")
            continue
        if not isinstance(value, dict):
            problems.append(f"line {number}: expected one JSON object, got {type(value).__name__}")
            continue
        try:
            record = EvalRecord.model_validate(value)
        except ValidationError as error:
            problems.append(f"line {number}: {_first_error(error)}")
            continue
        if record.record_id in ids:
            problems.append(
                f"line {number}: duplicate record_id {record.record_id} (first on line {ids[record.record_id]})"
            )
            continue
        ids[record.record_id] = number
        records.append(record)
    if not records and not problems:
        problems.append("the file has no records")

    documents: dict[str, tuple[str, str | None, str]] = {}
    for record in records:
        for doc in record.references:
            seen = documents.setdefault(doc.doc_id, (doc.text, doc.version, record.record_id))
            if (seen[0], seen[1]) != (doc.text, doc.version):
                problems.append(
                    f"{record.record_id}: document {doc.doc_id} differs from its copy in {seen[2]}"
                )
        by_id = {d.doc_id: d for d in record.references}
        for gold in record.gold_evidence:
            text = by_id[gold.doc_id].text
            sentences = [
                text[s.start : s.end]
                for s in sentence_spans(text, MAX_PASSAGE_CHARS)
                if s.start < gold.span.end and gold.span.start < s.end
            ]
            if any(instruction_like(s) for s in sentences):
                problems.append(
                    f"{record.record_id}: gold quote in {gold.doc_id} comes from an instruction, not a fact"
                )
        location = injection_location(record)
        tagged = INJECTION_TAGS & set(record.tags)
        if EvalCategory.PROMPT_INJECTION in record.categories:
            if location is None:
                problems.append(
                    f"{record.record_id}: categorised prompt_injection but contains no recognisable injection"
                )
            elif tagged and tagged != {location}:
                problems.append(
                    f"{record.record_id}: tagged {sorted(tagged)} but the injection is {location}"
                )
        elif location is not None or tagged:
            problems.append(
                f"{record.record_id}: contains an injection but is not categorised prompt_injection"
            )

    labels = Counter(r.expected_verdict.value for r in records)
    adversarial = [r for r in records if EvalCategory.PROMPT_INJECTION in r.categories]
    groups = Counter(r.expected_verdict.value for r in records if r not in adversarial)
    groups_out = {
        k: groups.get(k, 0) for k in ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE")
    } | {"adversarial": len(adversarial)}
    total = len(records)
    shares = {k: (v / total if total else 0.0) for k, v in groups_out.items()}
    coverage = {
        name: sum(1 for r in records if test(r)) for name, test in REQUIRED_COVERAGE.items()
    }
    if check_mix and records:
        if not SIZE_RANGE[0] <= total <= SIZE_RANGE[1]:
            problems.append(f"{total} records; EVAL.md asks for {SIZE_RANGE[0]}-{SIZE_RANGE[1]}")
        for group, target in TARGET_SHARES.items():
            if abs(shares[group] - target) > SHARE_TOLERANCE:
                problems.append(
                    f"{group}: {shares[group]:.1%} of records, target {target:.0%} ± {SHARE_TOLERANCE:.0%}"
                )
        problems += [f"no record covers: {name}" for name, n in coverage.items() if n == 0]
    return DatasetReport(
        path=str(path),
        records=total,
        problems=problems,
        labels={k: labels.get(k, 0) for k in ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE")},
        adversarial=len(adversarial),
        groups=groups_out,
        shares=shares,
        splits=dict(sorted(Counter(r.split.value for r in records).items())),
        categories=dict(sorted(Counter(c.value for r in records for c in r.categories).items())),
        coverage=coverage,
        injection_locations=dict(
            Counter(injection_location(r) for r in adversarial if injection_location(r))
        ),
        human_reviewed=sum(1 for r in records if r.reviewed_by),
    )


def summary(report: DatasetReport) -> str:
    lines = [
        f"{report.path}: {report.records} records, {'VALID' if report.ok else f'{len(report.problems)} problem(s)'}",
        "",
    ]
    lines += ["| Group | Records | Share | Target |", "|---|---|---|---|"]
    for group, n in report.groups.items():
        lines.append(f"| {group} | {n} | {report.shares[group]:.1%} | {TARGET_SHARES[group]:.0%} |")
    lines += [
        "",
        "Labels including adversarial records: "
        + ", ".join(f"{k} {v}" for k, v in report.labels.items()),
        "Splits: " + ", ".join(f"{k} {v}" for k, v in report.splits.items()),
        "Injection locations: "
        + ", ".join(f"{k} {v}" for k, v in report.injection_locations.items()),
        f"Human-reviewed labels: {report.human_reviewed}/{report.records}",
        "",
        "Coverage:",
    ]
    lines += [f"  {name}: {n}" for name, n in report.coverage.items()]
    lines += ["", "Problems:"] + [f"  - {p}" for p in report.problems] if report.problems else []
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m inkloom_verify.evaluation.dataset", description=__doc__.split("\n")[0]
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    try:
        report = validate_dataset(args.path)
    except OSError as error:
        print(f"error: cannot read {args.path}: {error.strerror}", file=sys.stderr)
        return 2
    print(report.model_dump_json(indent=2) if args.json else summary(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
