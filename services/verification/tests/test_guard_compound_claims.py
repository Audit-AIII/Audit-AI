"""Round 3 guard failure B: a compound claim whose quotes cover only one of its parts.

"Lumen Pods charge over USB-C and include a wireless charging pad" passes on "Charging: USB-C."
(dev record v1-045): half the claim has no support, yet the answer stays SUPPORTED. Compound
claims today only get a review flag (decision_policy.looks_compound). The case IDs follow
docs/round3/krish/04-fix-guard-compound-claims.md. The rule reads the claim and the quotes alone,
so every case here is checked with no passages.
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

REJECTED = {
    "C1": ("Lumen Pods charge over USB-C and include a wireless charging pad.", ["Charging: USB-C."]),
    "C2": (
        "The Lumen Bottle holds 750 ml and comes with a lifetime warranty.",
        ["Capacity: 750 ml."],
    ),
    "C3": (
        "Lumen Pods are rated IPX4 and are dishwasher safe.",
        ["Water resistance: IPX4 (splash resistant)."],
    ),
    "C4": ("The bottle weighs 340 g; it is made in Portugal.", ["Weight: 340 g."]),
    "C5": (
        "Lumen Pods weigh 5.2 g, cost 129 euro and come with a travel case.",
        ["Weight: 5.2 g per earbud. Price: 129 euro."],
    ),
    "C6": ("The case weighs 48 g and is waterproof.", ["The case weighs 48 g."]),
}

ACCEPTED = {
    "D1": (
        "Lumen Pods are rated IPX4 and charge over USB-C.",
        ["Charging: USB-C. Water resistance: IPX4 (splash resistant)."],
    ),
    "D2": ("Lumen Pods come in Graphite, Sand and Teal.", ["Colours: Graphite, Sand, Teal."]),
    "D3": ("The warranty lasts between 2 and 3 years.", ["Warranty: 2 to 3 years."]),
    "D4": (
        "The case and the earbuds together weigh 60 g.",
        ["The case and the earbuds together weigh 60 g."],
    ),
    "D5": ("Marks and Spencer sells Lumen Pods.", ["Marks and Spencer sells Lumen Pods."]),
    "D6": (
        "Lumen Pods charge over USB-C and have IPX4 water resistance.",
        ["Pods charge over USB-C and have IPX4 water resistance."],
    ),
    "D7": (
        "Lumen Pods launch on 2 April 2026 and cost 129 euro.",
        ["Launch date: 2 April 2026. Price: 129 euro (EU launch price)."],
    ),
}


@pytest.mark.parametrize("case", sorted(REJECTED))
def test_a_claim_part_no_quote_covers_is_rejected(case):
    claim, quotes = REJECTED[case]
    assert R.UNSUPPORTED_CLAUSE in support_problems(claim, quotes)


@pytest.mark.parametrize("case", sorted(ACCEPTED))
def test_a_claim_whose_parts_are_all_covered_is_accepted(case):
    claim, quotes = ACCEPTED[case]
    assert R.UNSUPPORTED_CLAUSE not in support_problems(claim, quotes)


def test_a_clause_sharing_one_incidental_word_with_the_quotes_is_rejected():
    # "recycled" is one of three content words of "ships in a recycled box": a part that long needs
    # at least half of them in the quotes, so one incidental word no longer covers it.
    claim = "The Lumen Bottle holds 750 ml and ships in a recycled box."
    quotes = ["Capacity: 750 ml. Made from recycled steel."]
    assert R.UNSUPPORTED_CLAUSE in support_problems(claim, quotes)


def _records():
    return [record for path in DATASETS for record in load_records(path)]


def test_v1_045_charging_pad_clause_is_rejected_on_its_reference_line():
    # v1-045 is labelled NOT_ENOUGH_EVIDENCE, so it has no gold quotes. A model that answers
    # SUPPORTED would cite the USB-C sentence of its reference, which covers half the claim.
    record = next(r for r in _records() if r.record_id == "v1-045")
    assert record.split is EvalSplit.DEV and record.expected_verdict is Verdict.NOT_ENOUGH_EVIDENCE
    assert not record.gold_evidence
    quote = "Charging: USB-C."
    assert any(quote in line for d in record.references for line in d.text.splitlines())
    assert R.UNSUPPORTED_CLAUSE in support_problems(record.claim_text, [quote])


def test_no_dev_supported_record_is_rejected_for_an_unsupported_clause_on_its_gold_quotes():
    # Dev only: held-out records must not steer the rule (00-START-HERE.md).
    supported = [
        r
        for r in _records()
        if r.split is EvalSplit.DEV and r.expected_verdict is Verdict.SUPPORTED
    ]
    assert len(supported) == 35
    rejected = [
        r.record_id
        for r in supported
        if R.UNSUPPORTED_CLAUSE
        in support_problems(r.claim_text, [g.quote for g in r.gold_evidence])
    ]
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
