# 05 — Evidence-grounded corrections

**Plan §3:** corrections must be grounded in evidence; validate for new unsupported facts and altered numbers; return uncertainty (not a guess) when evidence is insufficient.

**Most of this already exists. Your job is to prove it, close the gaps, and measure it.** Do not rewrite `correction.py`.

## Paste into Claude Code

> Read `docs/round3/krish/00-START-HERE.md`, then execute `docs/round3/krish/05-evidence-grounded-corrections.md`. First produce the gap table with a failing test per gap; only then change code. Stop at every STOP gate.

## What exists today (verified in `correction.py`)

| Plan requirement | Existing check |
|---|---|
| Only evidence-backed corrections | only CONTRADICTED results with validated citations are sent to the model; the model sees the sentence, claim and the justifying quotes only |
| No new unsupported facts | every word the replacement **adds** must appear in the cited quotes (grammar words exempt); same for currency/unit symbols → `UNSUPPORTED_ADDITION` |
| No altered numbers | a new figure with a unit must appear in the evidence **with that unit**; a new whole date must be a whole date of the evidence → `UNSUPPORTED_ADDITION` |
| Keep meaning | dropped unit, dropped attribution, dropped qualifier ("up to"), minimality bound (`NOT_MINIMAL`); `intent_lock.py` |
| Verified | the corrected claim must **re-verify as SUPPORTED** against the same evidence |
| Uncertainty | failures become `NEEDS_HUMAN_REVIEW` with reasons; provider failures `FAILED`; NOT_ENOUGH_EVIDENCE claims get no correction (optional "safer wording" only) |

(Open `correction.py` and confirm each row; fix this table in your notes if I misread something.)

## Step 1 — Find the gaps (read-only)

Hunt with tests, not by eye. Make a list, one failing test per confirmed gap. Candidates, in priority order:

1. **Bag-of-figures pairing (the same defect as step 03).** `mispaired` only asks whether `(number, unit)` appears *anywhere* in the evidence. Case: claim "keeps drinks cold for up to 12 hours", quote "keeps drinks cold for up to 24 hours and hot for up to 12 hours". A replacement of "…cold for up to 12 hours" → "…hot for up to 12 hours" style swaps, or a fix that **borrows the wrong figure** (e.g. replacing 12 by a figure that exists in the quote but belongs to another property), passes today. Reproduce with `correction_issues(original, replacement, quotes)`; step 01 already recorded this.
2. **Number added without a unit.** `mispaired` ignores figures whose unit is `None`. A bare "36" passes if "36" is a word in the quote. Test: replacement introducing a bare number that the quote uses for something else.
3. **Number *removed* silently.** Corrections that delete the figure instead of fixing it (the checker counts dropped *units*, not dropped *figures*). Test: "up to 12 hours" → "for many hours".
4. **Compound correction.** A replacement that fixes one clause and leaves a second unsupported clause: after the step-04 guard, the re-check should reject it; write a test that proves the re-check does use the new guard.
5. **Uncertainty path.** When the evidence only says the claim is *unsupported* (not contradicted), the output must be a hedge or nothing, never an asserted new fact. Confirm with a scripted provider that returns an asserted replacement for a NOT_ENOUGH_EVIDENCE claim: it must not be offered as a correction.

Output: `docs/round3/krish/corrections-gap-table.md` — gap, failing test name, current result, expected result. Only gaps with a **reproduced** failure go to Step 2.

**STOP F:** show the table. Commit tests red: `test: round 3 correction grounding gaps (red)`.

## Step 2 — Fix the confirmed gaps (smallest change each)

- Gap 1 and 2: **reuse** the step-03 binding function inside `correction_issues`: for each *new* figure in the replacement, apply the same "bound to another property?" test against the quotes (replacement context = `before + replacement + after`). Add a new `CorrectionIssueCode` only if no existing code fits. If you add one, it is an additive enum value and an additive change to the report schema: regenerate, update `CONTRACTS.md`, tell Darsh/Chahit.
- Gap 3: add a "figure dropped" issue only if the test shows it happening with the current prompt; do not add it speculatively.
- Gap 4/5: usually test-only (the checks exist; you are proving they are wired).

Same discipline as 03/04: no dataset strings in `src/`, no loosening of existing checks, REG entries (**REG-016** onwards), registry key set exact.

## Step 3 — Measure corrections (this is a deliverable, §5)

The repo already measures the checker (`baseline.json`: "correction checker: bad edits rejected / false accepts / good edits accepted") and traceability (`required_metrics`: correction traceability = traceable proposals ÷ proposed). Run and record:

```powershell
cd services\verification
.\.venv\Scripts\python eval\run_eval.py --check-baseline
.\.venv\Scripts\python eval\run_eval.py --verdicts oracle --check-baseline
```

Then extend the **checker dataset** (wherever the existing bad-edit/good-edit cases live — find it with `git grep -n "correctly_rejected"`) with your new gap cases: each reproduced gap becomes a *bad edit that must be rejected*; add at least as many *good edits that must be accepted* so the checker is not just made stricter. Report: bad edits rejected n/N, good edits accepted n/N, false accepts count. Tighten the baseline gates to the new measured numbers (never loosen).

For the final live evaluation (step 07) report, in the same table: corrections proposed, corrections that passed all checks, corrections needing review, and — **by reading them yourself** — how many of the offered corrections are actually correct. Label this human-read sample with its size and who read it. A model-generated correction judged only by code is a claim about *traceability*, not about *correctness*; say which one you are claiming.

## Done when

- [ ] Gap table with reproduced failures only
- [ ] Red-then-green commits; every fixed gap has a registered REG entry
- [ ] Checker dataset extended; bad-edits-rejected / good-edits-accepted / false-accepts reported with counts
- [ ] Baseline gates tightened only where measured
- [ ] Docs state what is claimed (traceability vs correctness)
