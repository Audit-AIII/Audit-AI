# 06 — Expand the benchmark beyond 80 and freeze the held-out set

**Plan §1 (bullets 3–4) and §6 ("expand, then freeze held-out, then final evaluation").**
Goal: a benchmark big enough that a held-out rate is defensible, with a held-out set that **nobody tuned against**.

## Paste into Claude Code

> Read `docs/round3/krish/00-START-HERE.md`, then execute `docs/round3/krish/06-expand-benchmark-and-freeze-heldout.md`. Do the validator/test changes first (Part A), author records in Part B only after I confirm the quotas, never run the engine on fresh held-out records before the freeze (Part D). Stop at every STOP gate.

## Why 120 and not "a bit more than 80" (decision CONFIRM #1)

Held-out today: 25 records, **only 7 SUPPORTED**. One SUPPORTED record moves the false-positive rate by **14.3 points**; "0/7" is also compatible with a true rate near 35%. With ~15 SUPPORTED in held-out, one record is ~6.7 points and the interval is still wide — say so in the report. If you want to go bigger, the cost is authoring + review time, not tooling; I chose 120 as the largest set one person can write *and get reviewed* in the time available. Change it if your deadline allows more or less.

## Part A — Make the tooling accept more than 100 records (code first, no new records yet)

Facts (verified): `evaluation/dataset.py` has `SIZE_RANGE = (50, 100)` and class shares `{SUPPORTED .30, CONTRADICTED .35, NOT_ENOUGH_EVIDENCE .25, adversarial .10}` ± 0.05. The validator treats **injection records as a separate "adversarial" group** (non-adversarial per label, plus adversarial). These tests hard-code 80: `tests/test_dataset_validation.py:289`, `test_run_eval.py`, `test_required_metrics.py:386`, `test_run_eval_pipeline.py:129,285,443`.

1. `git grep -n "80\b" -- services/verification/tests services/verification/src | grep -v "180\|800"` — list **every** hard-coded count.
2. Change `SIZE_RANGE` to `(50, 150)`. Nothing else in the validator changes (shares stay).
3. Replace each hard-coded `80` with a value derived from the dataset (`len(load_records(...))`) **or** with the new count, whichever the test intends (a test pinning "the dataset is the locked one" should pin the lock's count, not a literal).
4. Add a test: the validator accepts a 120-record synthetic mix and rejects 151.
5. Run the suite. It must be green on the **unchanged** 80 records before you add any.

Commit: `chore: let the benchmark grow past 100 records`.

## Part B — Author 40 new records (quotas)

| Group | New | Of which held-out ("fresh") | Notes |
|---|---|---|---|
| SUPPORTED | +12 | +9 | Include paraphrase, multi-figure, multi-document, date, unit cases. These drive the false-positive rate. |
| CONTRADICTED | +14 | +8 | numeric, near-miss, date, negation, outdated, unit, compound-one-part-wrong, conflicting references |
| NOT_ENOUGH_EVIDENCE | +10 | +6 | absent fact, ambiguous, irrelevant references, **claims that sound plausible** |
| Adversarial (injection) | +4 | +2 | one in content, one in a reference, mix |
| **Total** | **40** | **25** | held-out becomes 50: SUPPORTED 16, CONTRADICTED 18, NEE 14, adv. 2 (**verify with the validator**; shares are ±5 points) |

Mandatory content from the plan: supported, contradicted, insufficient-evidence, **numerical** and **compound** cases. Tag them with the existing `EvalCategory` values (`numeric`, `compound`, `near_miss`, `date`, `unit_mismatch`, …) so `REQUIRED_COVERAGE` stays satisfied.

Rules for writing records (all from the repo's own governance):
- IDs `v4-001…v4-040`. Fresh held-out records get the tag `v4_fresh` **and** `split: "heldout"`. (A free-form tag: confirm the schema allows it; if tags are a closed enum, use the next-version id prefix as the marker instead.)
- **Write the label before you see any engine output.** Do not run the engine on a fresh record while writing it. If you must sanity-check a claim, check it against the document by hand.
- Same synthetic company ("Lumen Goods") is fine, but add **new documents/facts** for at least half the new records; otherwise the benchmark mostly re-tests the same seven fact sheets. Document ids and text must not collide with existing ones.
- Never copy a failing claim from the earlier datasets or from a guard test of step 03/04. Tests may use them; held-out may not.
- Gold evidence: exact quote + character span in the document; `NOT_ENOUGH_EVIDENCE` records have empty `gold_evidence`.

### Builder script (throwaway, `%TEMP%` — do not commit)

The span and hash conventions I verified on `v1-001`: `text_sha256` = sha256 of the UTF-8 text; `span` indexes **Python characters** into `text`; `text[start:end] == quote`.

```python
import hashlib, json, sys
def record(rid, split, claim, verdict, docs, quote_doc_quote, rationale, categories, tags=()):
    refs = [{"doc_id": d, "version": "v1", "title": t, "text": x,
             "text_sha256": hashlib.sha256(x.encode()).hexdigest()} for d, t, x in docs]
    gold = []
    for doc_id, quote in quote_doc_quote:
        text = next(x for d, _, x in docs if d == doc_id)
        assert text.count(quote) == 1, f"quote must occur exactly once: {quote!r}"
        s = text.index(quote)
        gold.append({"doc_id": doc_id, "span": {"start": s, "end": s + len(quote)}, "quote": quote})
    return {"record_id": rid, "split": split, "claim_text": claim, "references": refs,
            "expected_verdict": verdict, "gold_evidence": gold, "label_rationale": rationale,
            "categories": list(categories), "tags": list(tags)}
```

(Check the exact field set against `schemas.py::EvalRecord` and `eval/dataset.jsonl` line 1; the validator is the judge, not this snippet.)

## Part C — Label review (this is what makes "labels" defensible)

Today every label is AI-written and **human-reviewed is 0/80**. For the 40 new records plus at least all held-out SUPPORTED/CONTRADICTED records:

1. Ask **Chahit or Darsh** (someone who did not write the record) to read claim + document and write their own verdict *without seeing yours*. Use a plain sheet: `record_id, reviewer_verdict`.
2. Disagreements: discuss, fix the **label or the claim** (it is a new record — editing is allowed before the freeze), record the outcome.
3. Set `reviewed_by` only on records that were actually reviewed; the reports then print "Human-reviewed labels: n/120" honestly. If only some are reviewed, say "n of N", never imply all.
4. Report the **agreement count** (e.g. 36/40 agreed before discussion). It is a limitation worth publishing.

## Part D — Hygiene so the held-out stays honest

1. **Tuning set for development:** create `eval/data/dev_only.jsonl` containing only `split == "dev"` records and use `run_eval.py --dataset eval/data/dev_only.jsonl` for all tuning (non-canonical, `check_mix=False`, no gates). Steps 03–05 should already use it from now on.
2. **Freeze file:** `eval/heldout.freeze.json` with the sorted held-out record ids, a SHA-256 of their label-bearing fields (id, claim, verdict, gold quotes), the count, and the date. Add `tests/test_heldout_freeze.py` that recomputes and compares. Changing a held-out record then fails a test, in addition to the lock.
3. **Lock:** update `eval/datasets.lock.json` (hash, count, label counts) in the **same commit** as the new records. Follow what `eval/datasets.lock.json` already contains per file; do not hand-edit hashes — regenerate with whatever `run_eval.py` / the lock test says (read `tests/test_run_eval.py:239–250` for the format).
4. **Baselines:** after the lock change, `--check-baseline` will need new numbers. Do not loosen a gate to make it pass. Re-measure on a deterministic mode (abstain / oracle), paste the numbers in the commit message, and tighten from those.
5. **Ledger:** create `docs/round3/results/RUN_LEDGER.md` (header: date, command, commit, model, split viewed, why). Every run that prints held-out metrics gets a line. The prototype I wrote during planning looked at 15 existing held-out SUPPORTED records once — write that down on the first line, with today's date, as honest disclosure.
6. **Existing 25 held-out are "used"**: they were visible during this planning and in prior team runs. The **fresh** 25 are the clean set. In step 07 report **both**: all-held-out (50) and fresh-only (25), with counts.

## STOP gates

**STOP G (before Part B):** confirm quotas with Krish (you) and that a reviewer is lined up for Part C.
**STOP H (before step 07):** `python -m inkloom_verify.evaluation.dataset eval/dataset.jsonl` passes, the full suite is green, lock + freeze committed, ledger created.

## Done when

- [ ] Validator accepts the new size; no hard-coded 80 remains
- [ ] 120 records; held-out ≈50 with ≥15 SUPPORTED; all required categories present (validator says so)
- [ ] Reviewer verdicts collected; `reviewed_by` set truthfully; agreement count recorded
- [ ] Lock, freeze file, dev-only file, ledger committed
- [ ] Baseline gates re-measured (tightened only)
- [ ] Docs (`EVAL.md` dataset section) updated with the new counts and the honest limitations (synthetic data, single company domain, reviewer count)
