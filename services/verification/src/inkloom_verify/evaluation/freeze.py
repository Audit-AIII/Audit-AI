"""Freeze of the held-out split (Round 3, step 06).

The label lock (eval/datasets.lock.json) stops any change to eval/dataset.jsonl. This file adds a
second, narrower guarantee: the held-out records' *labels* are fingerprinted on their own, so a
change to a held-out label fails a test that says so, and the fingerprint is published next to the
numbers. A fingerprint covers what a label means: the record id, the claim, the expected verdict,
the gold quotes with their spans, and the hash of every reference document.

Regenerate only when a held-out label is meant to change (for example after a reviewer disagrees),
and add a line to docs/round3/results/RUN_LEDGER.md saying why::

    python -m inkloom_verify.evaluation.freeze eval/dataset.jsonl --write eval/heldout.freeze.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from inkloom_verify.evaluation.runner import load_records
from inkloom_verify.schemas import EvalRecord, EvalSplit

FRESH_TAG = "v4_fresh"  # held-out records written in Round 3, never looked at while the rules were tuned


def label_fingerprint(record: EvalRecord) -> list[Any]:
    """Everything that makes up one label, in a fixed order."""
    gold = sorted((g.doc_id, g.span.start, g.span.end, g.quote) for g in record.gold_evidence)
    documents = sorted((d.doc_id, d.text_sha256) for d in record.references)
    return [record.record_id, record.claim_text, record.expected_verdict.value, gold, documents]


def digest(records: Iterable[EvalRecord]) -> str:
    rows = sorted((label_fingerprint(r) for r in records), key=lambda row: str(row[0]))
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def heldout_records(records: Sequence[EvalRecord]) -> list[EvalRecord]:
    return [r for r in records if r.split is EvalSplit.HELDOUT]


def fresh_records(records: Sequence[EvalRecord]) -> list[EvalRecord]:
    return [r for r in records if FRESH_TAG in r.tags]


def _group(records: Sequence[EvalRecord]) -> dict[str, Any]:
    ids = sorted(r.record_id for r in records)
    labels: dict[str, int] = {}
    for r in records:
        labels[r.expected_verdict.value] = labels.get(r.expected_verdict.value, 0) + 1
    return {"count": len(ids), "labels": dict(sorted(labels.items())), "record_ids": ids, "sha256": digest(records)}


def manifest(records: Sequence[EvalRecord], frozen_on: str) -> dict[str, Any]:
    return {
        "note": "Fingerprints of the held-out labels. A change to any held-out record fails "
        "tests/test_heldout_freeze.py. Regenerate only on purpose, with a line in "
        "docs/round3/results/RUN_LEDGER.md. 'fresh' records were written in Round 3 and were not "
        "used while the guard rules were tuned; the other held-out records were seen during earlier work.",
        "frozen_on": frozen_on,
        "labels_reviewed_by_a_person": sum(1 for r in heldout_records(records) if r.reviewed_by),
        "heldout": _group(heldout_records(records)),
        "fresh": _group(fresh_records(records)),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print or write the held-out freeze manifest.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--write", type=Path, help="write the manifest to this file")
    parser.add_argument("--date", default=date.today().isoformat(), help="frozen_on (default: today)")
    args = parser.parse_args(argv)
    text = json.dumps(manifest(load_records(args.dataset), args.date), indent=2, ensure_ascii=False) + "\n"
    if args.write:
        args.write.write_text(text, encoding="utf-8")
        print(f"wrote {args.write}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
