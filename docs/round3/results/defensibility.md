# Defensibility self-audit (runbook step 09, step 4)

Written 2026-10-29, on branch `krish/round3-reconcile` (commit `e9055a2`, plus the uncommitted
Phase 9 edits listed in `phase9-status.md`).

**There is no published result to defend yet.** Steps 06 (120-record benchmark, frozen held-out)
and 07 (three live full-pipeline runs) have not been done, so there is no headline number. The
answers below say what holds today and what can't be answered until those steps exist. Nothing
here is a measurement of model quality.

## Which records tuned the rules?

Dev records only, as far as the rules are concerned:

- The property-binding and compound-claim rules (REG-017/018) were designed on the step 03/04
  matrix cases (hand-written), main's REG-014/015 tests, and dev records `v1-036` and `v1-045`.
  Both records are `split: dev` (checked by `test_v1_036_…` and `test_v1_045_…`).
- The "0 of 35" checks run on dev SUPPORTED records only
  (`tests/test_guard_property_binding.py`, `tests/test_guard_compound_claims.py`).
- 12 probe cases (`tests/test_guard_probes.py`) were checked after the rules. Only R4, A6, A7 and
  A8 were written after the final rules; R1 shaped the rule for figures of other units.
- `test_every_gold_quote_still_supports_its_supported_claim` was restricted to dev records during
  the reconcile merge, because main's version read held-out gold quotes.

**Not dev-only:** the earlier, pre-runbook work read held-out gold quotes (ledger, line 1), and the
runbook's own prototype printed held-out SUPPORTED records once (`00-START-HERE.md`, "Disclosure").
That is why step 06 adds fresh held-out records.

## How many times was held-out viewed, and by whom?

Three logged looks, all on 2026-10-28, all by Krish's Claude Code sessions
(`docs/round3/results/RUN_LEDGER.md`):

1. pre-runbook work read the held-out SUPPORTED gold quotes;
2. one measurement in that work named held-out record `v3-023`;
3. a step 04 diagnostic named held-out record `v1-021`; the rule was not changed after it.

Plus the runbook author's prototype look disclosed in `00-START-HERE.md`. No look on 2026-10-29:
the baseline gates score every record, but no held-out record or held-out result was read.

## Would one more record change the headline? By how much?

No headline exists yet. On today's dataset (80 records; held-out 25: 10 CONTRADICTED,
8 NOT_ENOUGH_EVIDENCE, 7 SUPPORTED, counted from `eval/dataset.jsonl`), one held-out record
moves:

- the false-positive rate (denominator 7 SUPPORTED) by 1/7 = **14.3 points**;
- the catch rate (denominator 18 problematic) by 1/18 = **5.6 points**.

That is the reason for step 06's target of about 50 held-out records with at least 15
SUPPORTED. Confidence intervals can only be given once a run produces numerators.

## Is any number on screen typed by a human?

Not in the Scorecard code: `git grep -nE "catch_rate|\b0\.(8|9)[0-9]" audit-ai-final/frontend/app
audit-ai-final/frontend/components` finds only field names and animation constants (step 08
check). Every rate comes from `GET /api/evaluations/latest`, and the page's validator rejects a
malformed payload rather than defaulting a value (`lib/additions/evaluationRun.ts`).

**But the page does not show a real published run.** `/latest` serves only backend-stored runs,
whose coverage is always `verifier_only` (`services/api/src/inkloom_api/evaluation_runner.py`);
no route serves the engine's full-pipeline `summary.json` (step 08 not done).

## What does a wrong approval look like in the report, and where is it listed?

A wrong approval is a record predicted SUPPORTED whose label is not SUPPORTED. Each run writes:

- `report.md`: a **Wrong approvals** line (`evaluation/report.py:401`) and the confusion matrix;
- `summary.json`: `confusion`, and `review.auto_cleared_but_not_supported` (record ids);
- `reports/<timestamp>/cases.jsonl` (full-pipeline runs): one line per record with the expected
  and predicted verdicts, the claims, citations and corrections.

Report files are git-ignored. A published run must therefore be copied into the repo on purpose
(step 08, option 1).
