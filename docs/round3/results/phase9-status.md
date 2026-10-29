# Round 3 (Krish): Phase 9 status, 2026-10-29

**Verdict: the runbook is NOT complete.** Three of the five acceptance criteria fail, because
steps 06 (benchmark expansion and held-out freeze), 07 (three live full-pipeline runs) and 08
(Scorecard wired to the published run) have not been done. Steps 03 and 04 (both guard fixes) are
done and verified; step 05 (corrections) is done in part.

State audited: branch `krish/round3-reconcile` at `e9055a2`, pushed. The PR into main is not open
yet: `gh` isn't installed here, and the body is ready. It must not merge until Darsh and Chahit
approve the reason codes and the team answers about PR #25.

## Acceptance checklist

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Full pipeline evaluated | **FAIL** | No live full-pipeline run has completed. Every live attempt in the local reports failed its gates, and the rest are oracle, dry-run or abstain runs. The ledger has no step 07 entries; no cassette exists (`eval/cassettes/` is absent). The offline full-pipeline harness runs (`run_eval.py --check-baseline`, exit 0), but it scores scripted answers, not a model. |
| 2 | Both guard fixes have passing positive and negative regression tests | **PASS** | `tests/test_guard_property_binding.py` 14 passed (N1, N2, N3, N6, N8 rejected; P1–P3, P5, P7, P8 accepted; `v1-036`; 0 of 35 dev). `tests/test_guard_compound_claims.py` 17 passed (C1–C6 and the incidental-word case rejected; D1–D7 accepted; `v1-045`; 0 of 35 dev). `tests/test_guard_probes.py` 12 passed. REG-017/018 are in `eval/regressions.json`. CI is green on `e9055a2`. |
| 3 | Metrics reproducible by one command | **PARTIAL (counted as FAIL)** | `eval/run_eval.py --check-baseline` reproduces the offline gates by one command, including from a clean clone (`clean-clone-check.md`). But the step's meaning is a replay of a recorded live run (`--replay eval/cassettes/final-run1.jsonl`), and no recorded run exists, so the headline cannot be reproduced. |
| 4 | Frontend Scorecard renders real evaluation data | **FAIL** | The Scorecard renders backend data with no hardcoded numbers (step 08 grep is clean). But `/api/evaluations/latest` serves only backend-stored **verifier-only** runs, and no route serves an engine full-pipeline summary. The headline it shows is pooled, not held-out. The contract (`contracts.md` §17, §23) is still a draft awaiting Darsh and Chahit. |
| 5 | Held-out metrics published with counts, denominators, n, model/config, date, limitations | **FAIL** | No held-out result exists to publish. The engine summary has no held-out split or catch rate today (Phase 8 trace). |

## Validation run on 2026-10-29 (working tree)

| Check | Result |
|---|---|
| Engine suite | **2054 passed, 3 xfailed**, re-run after this phase's `limitations.py` edit; the same in a clean clone of `e9055a2` (`clean-clone-check.md`) |
| Clean-clone check | suite and both offline gates pass with no `.env` or keys; **the replay command fails (exit 2): no cassette exists** |
| `run_eval.py --check-baseline` | exit 0, no failing gate |
| `run_eval.py --verdicts oracle --check-baseline` | exit 0 |
| Dataset validator (`python -m inkloom_verify.evaluation.dataset eval/dataset.jsonl`) | exit 0 |
| Dataset, lock and regression-registry tests | 112 passed |
| `eval/dataset.jsonl`, `eval/datasets.lock.json`, `eval/data/` | unchanged since the runbook's start commit `1e416e5` and versus `origin/main` |
| Held-out frozen | **Unchanged, but no freeze file exists** (step 06 creates it). 25 held-out records: 10 CONTRADICTED, 8 NOT_ENOUGH_EVIDENCE, 7 SUPPORTED |
| Baseline gates | One change since `1e416e5`, a tightening: valid-quote false-SUPPORTED 0.2909 → 0.2545 (16/55 → 14/55, dev, scripted adversary). Nothing loosened. |
| Corrections evidence-grounded | `tests/test_correction_grounding.py` 21 passed; checker 28/28 bad rejected, 17/18 good accepted, 0 false accepts; gap candidates 6/6 and 10/10 |
| API contract | `routers/evaluations.py`, `evaluation_runner.py` and `API.md` are unchanged on this branch. One schema change: `verification_report.schema.json` guard reasons now list `property_mismatch` and `unsupported_clause`, and drop `unsupported_component`, which existed only on main via PR #25. The backend stores no guard reasons (Darsh, contracts.md §22). |
| CI on `e9055a2` | all jobs green, including the backend suite on real PostgreSQL |

## Metrics audit (step 3 of this phase)

There are **no three-run results**. Nothing below is a measurement of a live model.

- **Held-out sample size:** 25 records (7 SUPPORTED, 18 problematic), from `eval/dataset.jsonl`.
  The planned expansion to about 50 held-out with at least 15 SUPPORTED (step 06) is not done.
- **Numerators and denominators:** none published. One held-out record moves the false-positive
  rate by 14.3 points and the catch rate by 5.6 points (`defensibility.md`).
- **Metric definitions:** `contracts.md` §15, a draft awaiting the team's OK. Catch rate =
  flagged problematic ÷ problematic; false-positive rate (FPR-A) = flagged SUPPORTED ÷ SUPPORTED;
  `ERROR` counts as not flagged. The rename of the engine's other "false-positive rate" to
  "False-CONTRADICTED rate" (§15) has **not** been applied.
- **Model and configuration:** none chosen and run for step 07.
- **Evaluation dates:** offline gate runs only (2026-10-29, oracle and scripted).
- **Dataset version:** dataset v2, 80 records, locked (`eval/datasets.lock.json`); 0 of 80
  human-reviewed.
- **Held-out exposure history:** three logged looks on 2026-10-28 (`RUN_LEDGER.md`), plus the
  runbook author's disclosed prototype look (`00-START-HERE.md`).
- **Failed runs:** live attempts with free or flash-lite models on older commits, all failing
  their gates (citation validity, provider failures, or no verdict), visible in the git-ignored
  `services/verification/eval/reports/`. They are not published and must not be quoted.
- **Unreconciled:** `evaluation/limitations.py` "Live model quality" quotes one live
  verifier-only Gemini run (87.5% CONTRADICTED recall), while `EVAL.md` says no live run has been
  measured. Step 07, step 7 reconciles these; not done.

## Repository audit (step 4 of this phase)

- **Branch diff against main** (`git diff origin/main...HEAD`): 22 files, all Round 3 engine,
  backend-test and docs files. No frontend change. A plain `git diff origin/main HEAD` *looks*
  like it deletes frontend perf work; that is 8 newer teammate commits on main
  (`96600ea`..`fd90ca5`), not this branch. Main must be merged into this branch before the PR
  merges.
- **Secrets:** no real key pattern in tracked files. All 16 `sk-or-` hits are test fixtures or
  placeholders (`TEST-ONLY`, `0000SECRET…`, `your-new-…`); no `.env` is tracked.
- **Generated artifacts:** report output is git-ignored; none is tracked.
- **Dependencies:** none added.
- **Unintended API changes:** none (see the API contract row above).

## Changed in this phase (uncommitted)

- `services/verification/src/inkloom_verify/evaluation/limitations.py`: the "Backend review
  routing" entry was false: it said the backend routes on `verdict != SUPPORTED` only. The
  backend applies the engine's decision policy (`engine/pipeline.py:275`), so the entry is
  corrected and marked out of scope for this evaluation (contracts.md §21 asked for this fix).
- `docs/round3/results/phase9-status.md` (this file), `defensibility.md`, `clean-clone-check.md`:
  new.
- **Not changed, on purpose:** `EVAL.md`'s "80 records" and "not yet agreed" statements, and the
  root `README.md`. They are still true, and the runbook's edits ("120 records", the headline
  replay command) would only be true after steps 06 and 07.

## Unresolved items

1. **Step 06:** expand to 120 records, about 50 held-out with at least 15 SUPPORTED; label
   review with `reviewed_by` and an agreement count; freeze file; lock; validator cap; remove the
   hard-coded 80s in tests.
2. **Step 07:** choose a compliant model (`data_collection: deny`; needs OpenRouter credit), dry
   run (STOP I), smoke run, three full runs with cassettes and ledger lines, replay check, the
   published table, and the reconciliation of the two live-run accounts.
3. **Step 08:** engine summary gains a held-out `headline` block; backend serves the published
   summary as `EvaluationOut` (additive); Scorecard shows held-out k/N, coverage, model, dataset
   hash and limitations; QA case for `coverage: "full_pipeline"`; screenshot pair; STOP J
   sign-off.
4. **Contract approvals:** §21 messages to Darsh and Chahit are drafted, not sent; §23 items 1–3
   await Darsh; Chahit has not replied to anything. Nobody has OK'd the §15 metric definitions.
5. **Step 05, partly done:** the gap tests and fixes exist (REG-016, re-measured with the new
   rules), but they came from PR #25, not the runbook's red-then-green commits, and the
   corrections checker dataset was not extended.
6. **PR for `krish/round3-reconcile`:** open it (body ready), merge main's 8 new commits into
   it, and get the team's answer about PR #25.
7. **Docs that wait on steps 06 and 07:** root `README.md` headline paragraph and replay command;
   `EVAL.md` counts and held-out disclosure; the "False-CONTRADICTED rate" display rename;
   `DISCLOSURE.md` / `DEPLOYMENT_READINESS.md` model and cost lines.
8. **Step 10:** the governance and tone handoff notes aren't sent.
9. **Commit-message mismatch:** `b3dd2b8` on `krish/round3-guards`; history isn't rewritten
   (pushed).
