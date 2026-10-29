# Round 3 step 05: correction-grounding gap table (STOP F)

Measured on 2026-10-30, branch `krish/round3-corrections` from `main` at `e3a5e63`. `main`
already has the reconcile merge, so `correction_issues` runs the step 03 and 04 guard rules
(`property_mismatch`, `uncovered_clauses`). Every candidate was probed with variants against that
code before this table was written. Only reproduced failures get a red test.

## Gaps

| # | Runbook candidate | Status on `main` | Failing test (red) | Current result | Expected result |
|---|---|---|---|---|---|
| 1 | Bag-of-figures pairing: a fix that borrows another property's figure | **Closed** (REG-016, then REG-017 in `correction_issues`) | none; already pinned by `test_correction_grounding.py::test_a_figure_bound_to_another_property_is_an_unsupported_addition` | hot→24, cold→12, and the other-unit case (a "3 years" warranty figure given to battery life) are all `unsupported_addition` | same |
| 2 | Number added without a unit | **Closed**: `property_mismatch` treats a bare number as compatible with any unit | none; covered by the `number-only` case of the same test | bare 36 for an earbud, colours 4→5 where 5 is sizes, 40→52 where 52 is stores: all `unsupported_addition`. Colours 4→3: offered | same |
| 3 | **Number removed silently** | **Fixed (REG-019, 2026-10-30): `drops_figure`.** Was open, reproduced for figures **without a unit** | `tests/test_correction_gaps.py::test_a_figure_deleted_instead_of_fixed_is_refused` [count, headcount, ordinal]; `::test_a_deleted_figure_is_refused_before_any_recheck` [False, True] | "come in 4 colours" → "come in colours", "has 40 employees" → "has employees", "ranked 3rd" → "ranked": **no issue**. Through the corrector the "colours" edit is **proposed**, with re-checking off and after a SUPPORTED re-check | refused (`needs_human_review`) by the deterministic checks, before any re-check |
| 4 | Compound correction: the re-check uses the step 04 guard | **Covered** | none; `test_correction_grounding.py::test_the_recheck_still_refuses_an_untouched_unsupported_part` and `::test_the_guard_reason_behind_that_recheck_is_the_compound_rule` pass | re-check downgraded to NOT_ENOUGH_EVIDENCE, `recheck_not_supported` | same |
| 5 | Uncertainty path: no asserted fact for a NOT_ENOUGH_EVIDENCE claim | **Covered** | none; `test_correction_engine.py::test_corrector_is_never_invoked_for_other_verdicts`, `test_pipeline.py::test_only_contradicted_claims_are_sent_for_correction`, `test_softening.py::test_rule1_a_suggestion_that_adds_a_fact_is_refused`, `::test_rule5_the_result_is_never_changed_and_no_correction_is_added` pass | no correction call for SUPPORTED, NOT_ENOUGH_EVIDENCE or ERROR; safer wording refuses added facts and never sets a correction | same |

**Why gap 3 is open only without a unit.** A figure that loses its unit is already refused
(`drops_unit`): "12 hours" → "hours", "€99" → "the EU launch price", "up to 12 hours" → "for many
hours". The deleted unitless figure is caught by nothing: no word is added, no unit is lost, and
the re-check has no figure left to check.

**Guards for the fix, green today and staying green:**
`test_a_figure_fixed_or_replaced_by_the_evidence_is_still_offered` [count-fixed, headcount-fixed,
count-to-list]. "4 colours" → "Graphite, Sand and Teal" drops the figure too, but replaces it with
the evidence's own list. The fix must keep offering it; say if you disagree.

## Not reproduced or not a gap (no test)

- **An empty replacement** ("in 2025" → "") reports `no_change`. It is refused, but under a
  misleading code. Noted, not changed.
- **"launched in 2025" → "launched in April"**, quoting "2 April 2026": the wrong year is dropped,
  but what's left is true and comes from the evidence. Not counted as a gap.

## Decisions for step 2 (after "go")

1. **Issue code.** No existing code fits a dropped figure (`drops_unit` is about units). The
   runbook allows a new code only if none fits. A new `drops_figure` value would be additive to
   `CorrectionIssueCode` and the report schema, and would need `CONTRACTS.md` updated and Darsh
   and Chahit told.
2. **Prompt evidence.** The runbook says to add the issue "only if the test shows it happening
   with the current prompt". Shown here: the checker and the corrector offer it with a scripted
   model. **Not shown:** that the live correction prompt produces such an edit. No live run
   exists (step 07).

## The runbook's "What exists today" table, checked against `correction.py`

All six rows hold, with two updates:
- **"No altered numbers"** is now stricter than written: besides the unit pairing (`mispaired`,
  line 145) and whole dates, `property_mismatch` (line 155) checks which property a new figure
  belongs to, including bare numbers.
- **Compound parts:** `uncovered_clauses` (line 162) judges the parts the replacement writes,
  against the quotes and cited passages.
