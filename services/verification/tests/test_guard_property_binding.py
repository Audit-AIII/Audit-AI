"""Round 3 guard failure A: a figure in the claim that the quotes attach to a different property.

`support_problems` checks that each figure in a SUPPORTED claim is *present* in the quotes, not
what it is a figure *of*: "cold for up to 12 hours" passes on "cold for up to 24 hours and hot for
up to 12 hours" (dev record v1-036). The case IDs follow
docs/round3/krish/03-fix-guard-numeric-property-binding.md; the gaps (N4, N5, N7, P4, P6) are
prototype cases that were dropped. N2 (the elision swap) is added once the rule exists, as a plain
test or a strict xfail depending on whether the rule catches it.
"""

import re
from collections import Counter
from pathlib import Path

import pytest

from inkloom_verify.citation_guard import support_problems
from inkloom_verify.evaluation.runner import load_records
from inkloom_verify.schemas import EvalSplit, GuardRejectionReason, Verdict

R = GuardRejectionReason
ROOT = Path(__file__).resolve().parents[1]
DATASETS = (ROOT / "eval" / "dataset.jsonl", ROOT / "eval" / "data" / "retrieval_v1.jsonl")

COLD_HOT = "keeps drinks cold for up to 24 hours and hot for up to 12 hours"

REJECTED = {
    "N1": ("The Lumen Bottle keeps drinks cold for up to 12 hours.", [COLD_HOT]),
    "N3": (
        "Lumen Pods play for up to 24 hours per charge.",
        ["Battery life: up to 12 hours of playback per charge. The case adds up to 24 hours."],
    ),
    "N6": (
        "Lumen Pods have a 2 year warranty.",
        ["Battery degrades after 2 years of daily use. Warranty: 3 years."],
    ),
    "N8": ("Lumen Goods has 52 employees.", ["Lumen Goods has 48 employees and 52 stores."]),
}

ACCEPTED = {
    "P1": ("The Lumen Bottle holds 750 ml.", ["Capacity: 750 ml."]),
    "P2": ("The Lumen Bottle weighs 340 g.", ["Weight: 340 g."]),
    "P3": (
        "With the charging case, Lumen Pods provide up to 36 hours of playback.",
        [
            "Battery life: up to 12 hours of playback per charge. "
            "With the charging case: up to 36 hours."
        ],
    ),
    "P5": (
        "From 1 May 2026, Lumen Pods cost 119 euro in the EU.",
        ["From 1 May 2026, the EU price of Lumen Pods is 119 euro."],
    ),
    "P7": ("The Lumen Bottle keeps drinks cold for up to 24 hours.", [COLD_HOT]),
    "P8": ("The Lumen Bottle keeps drinks hot for up to 12 hours.", [COLD_HOT]),
}


@pytest.mark.parametrize("case", sorted(REJECTED))
def test_a_figure_bound_to_another_property_is_rejected(case):
    claim, quotes = REJECTED[case]
    assert R.PROPERTY_MISMATCH in support_problems(claim, quotes)


@pytest.mark.parametrize("case", sorted(ACCEPTED))
def test_a_figure_bound_to_the_claimed_property_is_accepted(case):
    claim, quotes = ACCEPTED[case]
    assert R.PROPERTY_MISMATCH not in support_problems(claim, quotes)


def _records():
    return [record for path in DATASETS for record in load_records(path)]


def test_v1_036_cold_figure_cited_from_its_full_reference_line_is_rejected():
    # v1-036's gold quote is only "keeps drinks cold for up to 24 hours", which the existing
    # quantity check already refuses for a 12-hour claim. The failure is a model citing the whole
    # line of the cited passage, which holds the 12 as well, but for "hot".
    record = next(r for r in _records() if r.record_id == "v1-036")
    assert record.split is EvalSplit.DEV and record.expected_verdict is Verdict.CONTRADICTED
    gold = record.gold_evidence[0]
    document = next(d.text for d in record.references if d.doc_id == gold.doc_id)
    line = next(line for line in document.splitlines() if gold.quote in line)
    assert "hot for up to 12 hours" in line
    problems = support_problems(record.claim_text, [line], [document])
    assert R.PROPERTY_MISMATCH in problems


def test_no_dev_supported_record_is_rejected_for_property_mismatch_on_its_gold_quotes():
    # Dev only: held-out records must not steer the rule (00-START-HERE.md); they are measured in
    # a report-only script, never asserted here.
    supported = [
        r
        for r in _records()
        if r.split is EvalSplit.DEV and r.expected_verdict is Verdict.SUPPORTED
    ]
    assert len(supported) == 35
    rejected = []
    for record in supported:
        documents = {d.doc_id: d.text for d in record.references}
        quotes = [g.quote for g in record.gold_evidence]
        cited = [documents[doc_id] for doc_id in dict.fromkeys(g.doc_id for g in record.gold_evidence)]
        if R.PROPERTY_MISMATCH in support_problems(record.claim_text, quotes, cited):
            rejected.append(record.record_id)
    assert rejected == []


# Mentions of the demo dataset's fictional company that were already in src/ before Round 3, all
# in comments, docstrings or the scripted test provider. The guard must stay generic: no new ones.
KNOWN_LUMEN_MENTIONS = Counter(
    {"citation_guard.py": 4, "security.py": 1, "evaluation/scripted.py": 1}
)


def test_the_guard_adds_no_dataset_specific_strings_to_src():
    src = ROOT / "src" / "inkloom_verify"
    found = Counter()
    for path in src.rglob("*.py"):
        hits = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if re.search("Lumen", line))
        if hits:
            found[path.relative_to(src).as_posix()] = hits
    assert found == KNOWN_LUMEN_MENTIONS
