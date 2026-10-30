"""Round 3 step 06: the held-out split is frozen, and tuning runs use a dev-only file.

A change to any held-out label (id, claim, verdict, gold quotes, reference text) fails here. If the
change is intended, regenerate eval/heldout.freeze.json (see evaluation/freeze.py) and add a line to
docs/round3/results/RUN_LEDGER.md saying why."""

import json
from pathlib import Path

from inkloom_verify.evaluation import freeze
from inkloom_verify.evaluation.runner import load_records
from inkloom_verify.schemas import EvalSplit, Verdict

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "eval" / "dataset.jsonl"
DEV_ONLY = ROOT / "eval" / "dev_only.jsonl"
FREEZE = ROOT / "eval" / "heldout.freeze.json"
RECORDS = load_records(DATASET)


def committed() -> dict:
    return json.loads(FREEZE.read_text(encoding="utf-8"))


def test_the_heldout_labels_match_their_freeze():
    now = freeze.manifest(RECORDS, committed()["frozen_on"])
    assert now == committed(), "a held-out label changed: regenerate the freeze on purpose and log why"


def test_the_fresh_records_are_all_heldout_and_all_round_3():
    fresh = freeze.fresh_records(RECORDS)
    assert len(fresh) == committed()["fresh"]["count"] == 25
    assert all(r.split is EvalSplit.HELDOUT and r.record_id.startswith("v4-") for r in fresh)
    assert not [r for r in RECORDS if r.record_id.startswith("v4-") and r.split is EvalSplit.DEV and freeze.FRESH_TAG in r.tags]


def test_the_heldout_split_is_big_enough_to_say_something_about_false_positives():
    """The reason for the expansion: with 7 SUPPORTED records one record moved the false-positive
    rate by 14 points. At least 15 SUPPORTED records are needed (about 6.7 points each)."""
    supported = [r for r in freeze.heldout_records(RECORDS) if r.expected_verdict is Verdict.SUPPORTED]
    assert len(supported) >= 15


def test_the_dev_only_file_is_exactly_the_dev_records_of_the_dataset():
    wanted = [
        line
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["split"] == "dev"
    ]
    assert DEV_ONLY.read_text(encoding="utf-8").splitlines() == wanted
    assert all(r.split is EvalSplit.DEV for r in load_records(DEV_ONLY))


def test_changing_a_heldout_label_changes_the_fingerprint():
    target = freeze.heldout_records(RECORDS)[0]
    flipped = target.model_copy(
        update={"claim_text": target.claim_text + " (edited)"}
    )
    assert freeze.digest([flipped]) != freeze.digest([target])
    other = Verdict.CONTRADICTED if target.expected_verdict is not Verdict.CONTRADICTED else Verdict.SUPPORTED
    assert freeze.digest([target.model_copy(update={"expected_verdict": other})]) != freeze.digest([target])
