# 03 — Fix guard failure A: numerical-property binding

**Plan §2 (first bullet) + §6 ("tests first").** Order inside this file is fixed: **tests (red) → commit → fix (green) → registry → gates.**

Failing record: `v1-036` (dev, CONTRADICTED). Claim "keeps drinks cold for up to **12** hours"; the quote says cold = 24 h, hot = 12 h. The guard accepts it because the number 12 is *present* in the quote.

## Paste into Claude Code

> Read `docs/round3/krish/00-START-HERE.md` (Rules, Ground truth), `docs/round3/krish/pipeline-audit.md`, then execute `docs/round3/krish/03-fix-guard-numeric-property-binding.md`. Write the tests first and show me them failing before you touch `citation_guard.py`. Stop at every STOP gate.

## Preconditions

- Step 01 done (baseline green, failure reproduced).
- Step 02 STOP C not required for this step, but the new reason code (below) is part of the contract: **tell Darsh and Chahit before you merge** (additive enum value; they must not crash on an unknown reason).

## The rule (what to implement)

Reject a SUPPORTED answer when **the evidence ties the claim's own property words to a different figure**. Not "figure absent" (already handled by `UNSUPPORTED_QUANTITY`), and not "words differ" (paraphrase is normal).

For each figure `F` in the claim (number + unit, via the existing `_QUANTITY` machinery):

1. `words(F)` = content words of the claim clause that holds `F`. If the previous clause has no number (an introductory phrase: "With the charging case,"), include it too.
2. `same` = evidence occurrences of the same number and compatible unit. `other` = evidence occurrences of a *different* number with a compatible unit.
3. If `same` is empty or `words(F)` is empty → do nothing (other checks own this).
4. If any `same` occurrence shares a word with `words(F)` (its own clause words **or** the `Label:` of its sentence) → OK.
5. Else if any `other` occurrence shares a word with `words(F)` → **reject** (`PROPERTY_MISMATCH`). The claim's property belongs to another figure.
6. Else → OK (unknown relation, stay quiet; this is what keeps false rejects at zero).

Definitions that matter (each one fixed a real false reject in prototyping):

| Piece | Rule | Why |
|---|---|---|
| Content words | tokenize (`retrieval.tokenize`), drop tokens with digits, qualifiers (`up to`, `about`, `at least`, `more than`…), unit words, stopwords; strip a plural `s` | numbers and hedges are not properties |
| Word match | equal, or shared 5-letter prefix (`weigh`/`weight`), or one startswith the other when both ≥4 letters | cheap stemming |
| Clause boundaries | `, ; : ( ) – —` and `and / but / while / whereas / plus` | stops one figure's words bleeding into the next |
| Sentence boundary | `.!?` and newline | stops bleed across sentences |
| `Label:` | the text before the first `:` of a sentence, only if ≤ 4 words; its words belong to **every** figure in that sentence | "Battery life: up to 12 hours…" |
| Label source in production | the line of the **cited passage** that contains the quote (the quote itself often omits its label) | quotes are substrings; labels sit just before |

### Known limit — write it down, do not hide it

An **elision swap** is *not* caught: claim "hot for up to **24** hours" against "cold for up to 24 hours and hot for up to 12 hours". Here `24`'s own clause contains "cold", not "hot", and nothing else ties "hot" to a different figure *in a way the rule can see without parsing*. In my prototype this was missed (case N2). Record it as a **strict xfail** test and a line in `evaluation/limitations.py` + `EVAL.md` (status `measured`). Do not claim the guard is complete.

## Step 1 — Write the tests FIRST (all of them red)

File: `services/verification/tests/test_guard_property_binding.py` (new). Import `support_problems` and `GuardRejectionReason`. Use the enum value name below (`PROPERTY_MISMATCH`); it does not exist yet, so the module will fail to import the member — create the **enum member only** in this step so the tests can run and fail on behaviour, not on import.

### Negative cases (must be REJECTED → `[PROPERTY_MISMATCH]` or contains it)

| ID | Claim | Quote(s) | Why |
|---|---|---|---|
| N1 | The Lumen Bottle keeps drinks cold for up to 12 hours. | keeps drinks cold for up to 24 hours and hot for up to 12 hours | **v1-036** |
| N3 | Lumen Pods play for up to 24 hours per charge. | Battery life: up to 12 hours of playback per charge. The case adds up to 24 hours. | case figure used for per-charge |
| N6 | Lumen Pods have a 2 year warranty. | Battery degrades after 2 years of daily use. Warranty: 3 years. | same number, other property |
| N8 | Lumen Goods has 52 employees. | Lumen Goods has 48 employees and 52 stores. | number belongs to "stores" |

### Positive cases (must be ACCEPTED → no `PROPERTY_MISMATCH`)

| ID | Claim | Quote(s) |
|---|---|---|
| P1 | The Lumen Bottle holds 750 ml. | Capacity: 750 ml. |
| P2 | The Lumen Bottle weighs 340 g. | Weight: 340 g. |
| P3 | With the charging case, Lumen Pods provide up to 36 hours of playback. | Battery life: up to 12 hours of playback per charge. With the charging case: up to 36 hours. |
| P5 | From 1 May 2026, Lumen Pods cost 119 euro in the EU. | From 1 May 2026, the EU price of Lumen Pods is 119 euro. |
| P7 | The Lumen Bottle keeps drinks cold for up to 24 hours. | keeps drinks cold for up to 24 hours and hot for up to 12 hours |
| P8 | The Lumen Bottle keeps drinks hot for up to 12 hours. | keeps drinks cold for up to 24 hours and hot for up to 12 hours |

(IDs skip N4/N5/N7/P4/P6 on purpose — those were prototype scratch cases I dropped. Keep the IDs as written so this file and your test names match.)

### Dataset-level tests (the ones judges will trust)

1. **Record test:** load `v1-036` with `load_records(...)`; build its gold quotes + cited passage; assert `support_problems` now contains `PROPERTY_MISMATCH`.
2. **No collateral damage:** for **every** record in `eval/dataset.jsonl` + `eval/data/retrieval_v1.jsonl` that is labelled `SUPPORTED` **and** `split == "dev"`, assert the new rule returns `[]` on its gold quotes. Measured on the prototype: **0 of 35**.
   Run the same loop for held-out SUPPORTED records **as a report-only script, not an assertion** (see the disclosure in `00-START-HERE.md`; held-out must not steer the rule).
3. **Strict xfail:** the elision swap (N2) with `@pytest.mark.xfail(strict=True, reason="declared limitation: elision swap; see EVAL.md")`.
4. **Reproducibility guard:** `grep -rn "Lumen" src/` returns nothing new (the rule must be generic).

### Run, expect red

```powershell
cd services\verification
.\.venv\Scripts\python -m pytest tests\test_guard_property_binding.py -q
```

Expected: N1, N3, N6, N8 and the `v1-036` record test **fail**; P-cases and the no-collateral test **pass** (they pass today because the rule does not exist yet).

**STOP D:** show me the failing output. Commit tests only: `test: round 3 guard property-binding regressions (red)`. Do not touch `citation_guard.py` before I say go.

## Step 2 — Implement (minimal)

1. `schemas.py` → `GuardRejectionReason`: add `PROPERTY_MISMATCH = "property_mismatch"` with a one-line comment ("a figure in the claim is attached to a different property in the quotes").
2. `citation_guard.py`: add `property_mismatch(claim, quotes, labels) -> bool` (or a small private module imported by it) following the rule table above. Pure function, no I/O, no dataset strings.
3. In `support_problems`, call it **after** the existing quantity/date/qualifier checks and add `PROPERTY_MISMATCH` once. Compute `labels` from `passages` when given (the line containing each quote); when `passages is None`, use no labels.
4. Do **not** change `verification.py`: it already runs `support_problems` for SUPPORTED answers only (`verification.py` ~L172–181). Check that claim in the code, do not trust me.

Reference sketch (prototype, not production — read it, then write your own version with docstrings and types):

```python
BREAK = re.compile(r"[,;:()–—]|\b(?:and|but|while|whereas|plus)\b", re.I)

def bound_problem(claim, evidence, evidence_label=""):
    ev = figure_contexts(evidence, evidence_label)                 # (num, unit, words, label_words)
    for num, unit, words, _ in figure_contexts(claim, is_claim=True):
        same  = [e for e in ev if e[0] == num and (unit is None or e[1] is None or e[1] == unit)]
        other = [e for e in ev if e[0] != num and (unit is None or e[1] is None or e[1] == unit)]
        if not same or not words: continue
        if any(stem_overlap(words, e[2] | e[3]) for e in same):  continue   # bound correctly
        if any(stem_overlap(words, e[2] | e[3]) for e in other): return True # bound to another figure
    return False
```

## Step 3 — Green, then measure

```powershell
.\.venv\Scripts\python -m pytest tests\test_guard_property_binding.py -q
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python eval\run_eval.py --check-baseline
.\.venv\Scripts\python eval\run_eval.py --verdicts oracle --check-baseline
.\.venv\Scripts\python -m inkloom_verify.json_schema
git diff --stat
```

Expected: new tests pass; full suite passes except tests that pin the old behaviour (list them, justify each); `v1-036` flips from wrong-approval to NOT_ENOUGH_EVIDENCE in the "valid-quote, always-SUPPORTED" stress run **[VERIFY: I did not run that stress run]**; the committed JSON schema changes by exactly one enum value.

**If a dev SUPPORTED record is newly downgraded: stop, do not loosen tests.** Narrow the rule (rule item 6 "unknown relation, stay quiet" and the clause boundaries are the dials) and re-run. Never delete the record or edit its label.

## Step 4 — Touchpoints (all of them, same commit)

- `schemas.py` enum (+ comment) · `schemas/verification_report.schema.json` (regenerate, do not hand-edit) · `CONTRACTS.md` (~L262 reason list) · `PROMPTS.md` (~L421 guard section: one paragraph, with the measured numbers) · `EVAL.md` (move `v1-036` from "open failure" to fixed; keep the elision limitation).
- `eval/regressions.json`: add **REG-014**: `id, found, phase, category: "numeric_discrepancies", title, symptom, fix, tests[], status: "fixed"` (exactly these keys; `tests/test_regression_registry.py` enforces the key set, the `REG-\d{3}` format, and that every listed test function exists). Reference the real test names.
- `eval/baseline.json`: only if a measured gate improved. Tighten, never loosen. Gate changes need the numbers from a real run pasted in the commit message.
- Backend/frontend: confirm (from the step 01 grep) that nothing switches on a closed list of reasons.

## Done when

- [ ] Tests existed and failed before the fix (commit order proves it)
- [ ] N1, N3, N6, N8 rejected; P1–P3, P5, P7, P8 accepted; `v1-036` flips; 0 dev SUPPORTED newly downgraded
- [ ] N2 recorded as strict xfail + limitation text
- [ ] REG-014 added, schema regenerated, docs updated, Darsh/Chahit told about the new reason
- [ ] Full suite + both `--check-baseline` runs green
- [ ] Commits: `test: …(red)` then `fix: guard rejects figures bound to another property` (+ attribution lines)
