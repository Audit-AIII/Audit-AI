# 04 — Fix guard failure B: compound claims

**Plan §2 (second bullet).** Same order as step 03: **tests (red) → commit → fix (green) → registry → gates.**

Failing record: `v1-045` (dev). Claim "Lumen Pods charge over USB-C **and include a wireless charging pad**"; the cited quote covers only "Charging: USB-C." Half the claim is unsupported, yet the guard says SUPPORTED. Today compound claims only get a *review flag* (`decision_policy.py` L58–102, `compound_under_cited`); the verdict stays SUPPORTED, so the Scorecard counts it as a wrong approval.

## Paste into Claude Code

> Read `docs/round3/krish/00-START-HERE.md` (Rules, Ground truth), `docs/round3/krish/pipeline-audit.md`, then execute `docs/round3/krish/04-fix-guard-compound-claims.md`. Tests first, show them red, stop at every STOP gate.

## Two layers, in this order

1. **Guard (do this):** a SUPPORTED answer is downgraded when a part of the claim is not covered by the cited quotes.
2. **Extraction (measure first, change only if needed):** the extraction prompt asks for one fact per claim, but no code enforces it. Layer 1 protects you even when extraction fails to split.

## The rule (layer 1)

Applies to **SUPPORTED answers only** (same place as `support_problems`).

**Works on the quotes alone** (amended 2026-10-28): the rule reads only the claim and the cited quotes. It must not need `passages`: `support_problems(claim, quotes)` with `passages=None` must still return `UNSUPPORTED_CLAUSE` for C1–C6. (The unmerged reference branch `krish/round3-prior-work` only fired when passages were given, and missed every C case without them.)

1. **Split** the claim at `and / but / while / whereas / plus / as well as` and `;` into parts.
2. **Subject** = the leading run of capitalised words ("Lumen Pods", "The Lumen Bottle"). Its words never count as coverage.
3. A part is **qualifying** only if it has ≥1 non-subject content word **and** is not a bare list item (all tokens capitalised: "Graphite", "Marks"). If the claim has **fewer than 2 qualifying parts → rule does not apply.**
4. A qualifying part is **covered** if it shares a *figure* (a number from `quantities`) with the quotes, **or** a non-subject content word with the quotes' **value text**.
5. **Value text** = the quotes with short `Label:` heads removed (label ≤ 4 words before the first colon). This is the key detail: label "Charging:" must not cover "a wireless charging pad". Without it v1-045 is missed.
6. If any qualifying part is uncovered → add `UNSUPPORTED_CLAUSE`.

Content words: same helper as step 03 (tokenize, drop digits/qualifiers/units/stopwords, strip plural `s`). Word match for coverage is **exact** here (no prefix matching): looser matching let "wireless charging pad" be covered by "charging".

### Why "≥ 1 word" and not "≥ 2"

A one-word predicate ("…and is waterproof") is exactly the kind of invented half-claim to catch. The "not a bare list item" test is what keeps "Graphite, Sand and Teal" and "Marks and Spencer" from being treated as clauses.

### Known limits — write them down

- A claim whose second clause shares one incidental word with the quote is **covered** (e.g. "…and ships in a recycled box" against a quote that contains "recycled"). Lexical overlap is a floor, not entailment.
- The rule never *proves* a clause is supported; it only catches clauses with **no** support in the quotes. Say this in `EVAL.md`.

## Step 1 — Write the tests FIRST

File: `services/verification/tests/test_guard_compound_claims.py` (new). Create the enum member `UNSUPPORTED_CLAUSE = "unsupported_clause"` first so the tests fail on behaviour.

### Negative cases (must contain `UNSUPPORTED_CLAUSE`)

| ID | Claim | Quote(s) |
|---|---|---|
| C1 | Lumen Pods charge over USB-C and include a wireless charging pad. | Charging: USB-C. | *(v1-045)*
| C2 | The Lumen Bottle holds 750 ml and comes with a lifetime warranty. | Capacity: 750 ml. |
| C3 | Lumen Pods are rated IPX4 and are dishwasher safe. | Water resistance: IPX4 (splash resistant). |
| C4 | The bottle weighs 340 g; it is made in Portugal. | Weight: 340 g. |
| C5 | Lumen Pods weigh 5.2 g, cost 129 euro and come with a travel case. | Weight: 5.2 g per earbud. Price: 129 euro. |
| C6 | The case weighs 48 g and is waterproof. | The case weighs 48 g. |

### Positive cases (must NOT contain it)

| ID | Claim | Quote(s) |
|---|---|---|
| D1 | Lumen Pods are rated IPX4 and charge over USB-C. | Charging: USB-C. Water resistance: IPX4 (splash resistant). |
| D2 | Lumen Pods come in Graphite, Sand and Teal. | Colours: Graphite, Sand, Teal. |
| D3 | The warranty lasts between 2 and 3 years. | Warranty: 2 to 3 years. |
| D4 | The case and the earbuds together weigh 60 g. | The case and the earbuds together weigh 60 g. |
| D5 | Marks and Spencer sells Lumen Pods. | Marks and Spencer sells Lumen Pods. |
| D6 | Lumen Pods charge over USB-C and have IPX4 water resistance. | Pods charge over USB-C and have IPX4 water resistance. |
| D7 | Lumen Pods launch on 2 April 2026 and cost 129 euro. | Launch date: 2 April 2026. Price: 129 euro (EU launch price). |

All 13 matched expectations in the prototype.

**Cases the earlier code taught us** (confirmed present above, 2026-10-28). The unmerged reference branch `krish/round3-prior-work` got these wrong, so they must stay in the matrix:
- **C6** must be rejected (a one-word predicate, "is waterproof", is a whole invented clause);
- **D1** must be accepted (subject words, "Lumen Pods", never count as uncovered);
- **D2** must be accepted (a list of capitalised items is not a set of clauses);
- **D3** must be accepted (a range, "between 2 and 3", is one fact).

### Dataset-level tests

1. **Record test:** `v1-045` is labelled NOT_ENOUGH_EVIDENCE and has **no gold quotes**, so use its reference line `"Charging: USB-C."` as the quote (load the record, take that line from its reference text, and assert it is there). With the record's claim and that quote alone (no passages) → `UNSUPPORTED_CLAUSE` present.
2. **No collateral damage:** every dev + `retrieval_v1` record labelled SUPPORTED → rule returns `[]` on its gold quotes. Prototype: **0 of 35** (the earlier, looser version downgraded 23 of 35 and then 1 of 35; the label-exclusion rule fixed the last one).
3. **Held-out is report-only** (same disclosure as step 03: prototype showed 0 of 15 held-out SUPPORTED newly downgraded; this does not make it tuning-free, which is why step 06 adds fresh records).
4. **Strict xfail** for the incidental-word limit above.
5. No dataset strings in `src/`.

**STOP E:** show red output. Commit `test: round 3 guard compound-claim regressions (red)`.

## Step 2 — Implement

1. `schemas.py`: add `UNSUPPORTED_CLAUSE = "unsupported_clause"` (comment: "a part of the claim is covered by none of the cited quotes").
2. `citation_guard.py`: `uncovered_clauses(claim, quotes) -> list[str]`, pure, typed, documented with the measured numbers.
3. `support_problems`: if non-empty, append the reason once.
4. Leave `decision_policy.looks_compound` alone: it still adds a review reason for compound claims that pass. Both layers stay.

## Step 3 — Extraction layer: measure before changing

Write a **scripted-provider test** (see `providers/fake.py`, `evaluation/scripted.py`) that feeds extraction a model reply containing the unsplit sentence. Record in `pipeline-audit.md`: does the pipeline (a) split it, (b) pass it through whole? Expected: (b), because nothing enforces atomicity.

- If (b) and layer 1 now catches it → **done**; add a note, do not touch extraction.
- If you still want atomicity, the smallest change is a *flag*, not a rewrite: after extraction, mark claims with ≥2 qualifying parts so the report shows they were unsplit. Needs an owner decision (it touches the report contract → STOP C rules apply).

## Step 4 — Green, measure, touchpoints

Same commands and touchpoint list as step 03 (suite, `--check-baseline` ×2, `json_schema`, `CONTRACTS.md`, `PROMPTS.md`, `EVAL.md`), plus:

- `eval/regressions.json` **REG-015**, category `compound_claims`, exact key set, real test names.
- `v1-045` moves from "open failure" to fixed in `EVAL.md`.
- `tests/test_known_limitations.py` / `evaluation/limitations.py`: add the incidental-word limitation as `measured`.
- If any dev SUPPORTED record is newly downgraded: **stop**; narrow the rule; never edit the record.

## Done when

- [ ] Red-then-green commit pair
- [ ] C1–C6 rejected, D1–D7 accepted, `v1-045` flips, 0 dev SUPPORTED newly downgraded
- [ ] Extraction behaviour measured and recorded; no unnecessary rewrite
- [ ] REG-015, schema, docs, limitations updated; teammates told about `unsupported_clause`
- [ ] Full suite + both baseline checks green
