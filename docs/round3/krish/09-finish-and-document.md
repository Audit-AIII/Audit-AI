# 09 — Finish: deliverables checklist and documentation

**Plan §5 (deliverables) and Round 3 requirement 6 (someone else must be able to clone the repo and run it from the README).**

## Paste into Claude Code

> Read `docs/round3/krish/00-START-HERE.md` and `docs/round3/krish/09-finish-and-document.md`. Go through the checklist, produce evidence for each line (command + output or file path), and fix only documentation unless a check fails. Stop at every STOP gate.

## Step 1 — Deliverables, one line of evidence each (plan §5)

| Deliverable | Evidence to attach |
|---|---|
| Expanded, documented benchmark + reproducible eval command | `EVAL.md` dataset section updated (counts, splits, reviewers, limitations); the exact command; replay reproducing a recorded run (step 07 §5) |
| Regression tests for both guard failures | `tests/test_guard_property_binding.py`, `tests/test_guard_compound_claims.py`, REG-014/015 in `eval/regressions.json`; suite output |
| Correction-validation checks and tests | step 05 gap table, new tests, REG entries, checker numbers with counts |
| Held-out catch / FPR with counts and limitations | the step 07 table, copied from `summary.json` |
| Agreed Scorecard API/data contract | `docs/round3/contracts.md` + acknowledgements; `services/api/API.md` additions |

## Step 2 — Final verification run (from a clean clone)

```powershell
git clone <repo> %TEMP%\verify-clone ; cd %TEMP%\verify-clone\services\verification
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]" -c constraints.txt
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python eval\run_eval.py --check-baseline
.\.venv\Scripts\python eval\run_eval.py --verdicts oracle --check-baseline
.\.venv\Scripts\python eval\run_eval.py --replay eval\cassettes\final-run1.jsonl
```

Everything must pass without your `.env`, your key or your machine's state. Record the output in `docs/round3/results/clean-clone-check.md`. If a step needs something undocumented, fix the README, not your machine.

## Step 3 — Documentation (what a stranger needs)

1. **Root `README.md`:** one paragraph on what the engine measures and one command to reproduce the headline number offline (the replay command).
2. **`services/verification/EVAL.md`:** update counts (120 records, splits), the new reason codes, REG-014+ entries, the metric definitions (and the renamed "false-CONTRADICTED rate"), the held-out disclosure and run ledger link. Remove or reconcile any statement that the new work makes false (search for `80`, `v1-036`, `v1-045`, "open failure", "not yet agreed").
3. **`DISCLOSURE.md` / `DEPLOYMENT_READINESS.md`:** keep them true: model used, `data_collection: deny`, costs, rate limits, what is synthetic.
4. **Limitations (be specific, this is what earns trust):**
   - Dataset is synthetic, single fictional company, labels AI-written; reviewed n of N; reviewer agreement count.
   - Held-out size → intervals (give them). Existing 25 held-out were visible during planning; fresh 25 are the clean set.
   - Guard rules are lexical heuristics: known misses (elision swap; incidental word coverage), declared with strict xfail tests.
   - Correction checks prove traceability, not truth; human-read sample size.
   - Backend routing still uses `verdict != SUPPORTED` unless Darsh changed it (`DECISIONS.md` single-user decision).
   - One model/provider; results can change with the model.
5. **Docs commit hygiene:** small commits, each with the Co-Authored-By trailer; no generated reports or keys.

## Step 4 — Self-audit against "defensible"

Answer in `docs/round3/results/defensibility.md`, with evidence, each question a judge could ask:
- Which records tuned the rules? (dev only; ledger)
- How many times was held-out viewed, by whom? (ledger)
- Would one more record change the headline? By how much? (counts and intervals)
- Is any number on screen typed by a human? (grep + payload check)
- What does a wrong approval look like in the report, and where is it listed? (`cases.jsonl` failures)

## Done when
- [ ] All five deliverables have evidence
- [ ] Clean-clone check passes from the README alone
- [ ] Docs contain no stale numbers; limitations are specific
- [ ] `defensibility.md` written
