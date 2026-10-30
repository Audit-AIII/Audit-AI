"""Compare a reviewer's verdicts with the dataset's labels (Round 3 step 06, Part C).

    python eval/review_agreement.py docs/round3/review/label-review-answers.csv

Prints how many verdicts agreed *before any discussion*, and lists every disagreement. It changes
nothing: setting ``reviewed_by`` on a record, or fixing a label after a disagreement, is a separate,
logged change (the label lock and the held-out freeze both have to be regenerated with it).
Blank rows (items the reviewer has not answered yet) are reported, not counted as agreement.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent.parent.parent
VERDICTS = {"SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("answers", type=Path)
    parser.add_argument("--key", type=Path, default=ROOT / "docs/round3/review/label-review-key.csv")
    parser.add_argument("--dataset", type=Path, default=EVAL / "dataset.jsonl")
    args = parser.parse_args(argv)

    records = {}
    for line in args.dataset.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            records[record["record_id"]] = record
    key = {row["item"]: row["record_id"] for row in csv.DictReader(args.key.open(encoding="utf-8", newline=""))}

    agreed, disagreed, blank, invalid = [], [], [], []
    for row in csv.DictReader(args.answers.open(encoding="utf-8", newline="")):
        item, verdict = row["item"], row["reviewer_verdict"].strip().upper()
        if not verdict:
            blank.append(item)
        elif verdict not in VERDICTS:
            invalid.append((item, row["reviewer_verdict"]))
        elif verdict == records[key[item]]["expected_verdict"]:
            agreed.append(item)
        else:
            disagreed.append((item, key[item], records[key[item]]["expected_verdict"], verdict, row.get("notes", "")))

    answered = len(agreed) + len(disagreed)
    print(f"Answered: {answered} of {len(key)} items; blank: {len(blank)}; invalid: {len(invalid)}")
    print(f"Agreed with the AI-written label before discussion: {len(agreed)}/{answered}")
    for item, record_id, label, verdict, notes in disagreed:
        print(f"  DISAGREE {item} ({record_id}): label {label}, reviewer {verdict}. {notes}")
    for item, raw in invalid:
        print(f"  INVALID {item}: {raw!r}")
    return 1 if invalid else 0


if __name__ == "__main__":
    sys.exit(main())
