# Round 3 step 01: pipeline audit and failure paths

Audited 2026-10-28 against commit `1e416e5089bccff6e5704093cbe97c86f8e05eab` (HEAD of `main`).
This step changed no production code.

> **Read first: the working tree is not clean.** Before this runbook was in the repo, Claude Code
> had already implemented uncommitted changes for steps 03, 04 and 05 (citation guard, correction
> checks, new guard reason `unsupported_component`, REG-014/015/016). They are **not** part of
> this audit. Every result below was produced on an exact export of HEAD (`git archive HEAD` into
> `%TEMP%`), so it describes the code as committed. See "State of the working tree" at the end.

## 1. Baseline (Step 1)

Run from `services/verification` on the HEAD export, with the repo's `.venv` and
`PYTHONPATH=<export>/src`:

| Command | Result | Exit |
|---|---|---|
| `python -m pytest -q` | 1952 passed, 1 skipped, 3 xfailed, **1 failed** (see note) | 1 |
| `python eval/run_eval.py --check-baseline` | all gates pass | 0 |
| `python eval/run_eval.py --verdicts oracle --check-baseline` | all gates pass | 0 |
| `git rev-parse HEAD` | `1e416e5089bccff6e5704093cbe97c86f8e05eab` | 0 |

**Note on the one failure:** `tests/test_ci_workflow.py::test_the_repository_has_no_conflict_markers_now`
runs `git grep`, and the export isn't a git repository (`fatal: not a git repository`, exit 128).
The check itself passes on the real repo: `git grep -nE "^(<<<<<<<|>>>>>>>)" HEAD` returns
exit 1 (nothing found), and the test passes there. **Baseline: 1953 passed / 1 skipped / 3
xfailed, matching the runbook's reference. STOP A not triggered.**

## 2. Stage map (Step 2, every row checked in the HEAD code)

| Stage | Module / entry point | Deterministic guard on its output | Tests |
|---|---|---|---|
| Extraction | `extraction.py` `ClaimExtractor.extract` (L297). Default prompt **`extract-claims-v1`** (`prompts/extraction.py` L10); `v2` is used only when `run_eval.py --prompts v2` pins it. **Corrected from the runbook, which said v2.** | `rewrite_problems` (L214), `locate` (L246): a claim must be traceable to its source span. **No atomicity check.** | `test_extraction.py`, `test_extractor_prompt.py`, `test_extraction_eval.py` |
| Retrieval | `retrieval.py` `BM25Retriever.for_request` (L139); `chunking.py` | recall gates in `eval/baseline.json` | `test_retrieval.py`, `test_retrieval_eval.py` |
| Verification | `verification.py` `ClaimVerifier.verify` (L102), `verify_claim` (L256) | `citation_guard.py` `CitationGuard.check` (L126), `support_problems` (L318), `conflicting_passage` (L375) | `test_verification.py`, `test_citation_guard.py`, `test_verifier_prompt.py` |
| Correction | `correction.py` `ClaimCorrector.correct` (L240); `intent_lock.py` | `correction_issues` (L109): unsupported additions, dropped unit, qualifier or attribution, minimality; then re-verify as SUPPORTED | `test_correction.py`, `test_correction_engine.py`, `test_correction_safety.py`, `test_intent_lock.py` |
| Safer wording | `softening.py` `ClaimSoftener.soften` (L246), NOT_ENOUGH_EVIDENCE only, **off by default** (`PipelineConfig.suggest_safer_wording = False`, `pipeline.py` L84) | `softening_issues` (L159) | `test_softening.py` |
| Decision policy | `decision_policy.py` `apply_policy` (L106) | adds review reasons only, never removes one (`ClaimResult` contract) | `test_decision_policy.py` |
| Report | `pipeline.py` `verify_request` (L91), `_run` (L136), `_report` (L332); `schemas.py` | `scope.py` `check_report_scope` (L101), called at `pipeline.py` L105 | `test_pipeline.py`, `test_report.py`, `test_report_generation.py` |
| Evaluation | `evaluation/runner.py`, `pipeline_predictor.py`, `required_metrics.py`, `summary.py`, `report.py`; `eval/run_eval.py` | label lock (`datasets.lock.json`) + baseline gates | `test_run_eval.py`, `test_run_eval_pipeline.py`, `test_required_metrics.py` |

The runbook's row for the safer-wording stage was missing; it was added above.

**Which stages call the model.** Extraction, verification, correction (and its re-check, which is
a second verification call), and safer wording. Retrieval, chunking, the citation guard, the
correction checks, the decision policy and the scope check are deterministic.

**Provider failure.** `ClaimVerifier.verify` catches `ProviderError` (`verification.py` L131) and
returns a `ClaimResult` with `verdict=ERROR` and the error (L253). Anything else that is raised for
one claim becomes `ERROR` in `pipeline._run` (`_claim_error`); a correction failure becomes a
`failed` correction attempt and keeps the verdict. Nothing on these paths produces `SUPPORTED`.
Pinned by `services/verification/tests/test_partial_failure.py` and
`services/api/tests/test_provider_failure_never_approved.py` (both present at HEAD).

**What verifier-only skips.** `run_eval.py --pipeline verifier` runs retrieval → verifier →
citation guard per record. It skips extraction (the record's claim is verified as written),
corrections and the re-check, safer wording, and the decision policy. The backend Scorecard uses
this path (`evaluation_runner.py` L58 `COVERAGE_VERIFIER_ONLY`, returned at L240).

## 3. Failure A: a figure bound to the wrong property (reproduced)

Script: `%TEMP%\...\scratchpad\r3_step01_repro.py` (throwaway), run on the HEAD export.

```
quantities(claim) = {('12', 'hour')}   quantities(quote) = {('12', 'hour'), ('24', 'hour')}
support_problems("The Lumen Bottle keeps drinks cold for up to 12 hours.",
                 ["keeps drinks cold for up to 24 hours and hot for up to 12 hours"]) = []
```

Real record `v1-036`: **dev**, CONTRADICTED, gold `keeps drinks cold for up to 24 hours`. Its
reference line is `Insulation: keeps drinks cold for up to 24 hours and hot for up to 12 hours.`;
`support_problems` on that line, with the document as the passage, also returns `[]`.

**Why.** `quantities()` (`citation_guard.py` L268) returns a *set* of `(number, unit)` pairs with no
link to the words around each number. `support_problems` (L318) builds `number → units` from that
set and only tests membership (L329–337): `12 hour` is in the quote, so the check passes, although
the quote gives 12 hours for *hot*.

**Same defect in corrections.** `correction_issues` (`correction.py` L131–136) accepts a new figure
if `(number, unit)` is in the evidence anywhere. On the same quote, a correction of a cold claim
`"6 hours" → "12 hours"` (the hot figure) returns `[]`, so it would be offered.

## 4. Failure B: a compound claim half-supported (reproduced)

```
support_problems("Lumen Pods charge over USB-C and include a wireless charging pad.",
                 ["Charging: USB-C."]) = []
```

Real record `v1-045`: **dev**, NOT_ENOUGH_EVIDENCE. With its real reference line
(`Charging: USB-C. A 10-minute charge gives up to 2 hours of playback.`) and the documents as
passages, also `[]`. No figure, date, qualifier, name or negation differs, so no support check
fires.

**What does look at compounds.** Only `decision_policy.py`: `looks_compound` (L80, regex L58) and
`COMPOUND_UNDER_CITED` (L102). For a SUPPORTED, strong-evidence answer:

| Accepted citations | Review reasons added | Verdict |
|---|---|---|
| 1 | `compound_under_cited` | SUPPORTED |
| 2 (any second quote) | none | SUPPORTED, can be auto-cleared |

It only adds a review reason; **the verdict stays SUPPORTED**, and the Scorecard counts verdicts,
so it is still a wrong approval.

**Extraction** (`r3_step01_extract.py`, scripted provider through `ClaimExtractor`):
- model returns two claims → 2 claims, spans `0–28` and `33–64`, no errors;
- model returns the sentence unsplit → **1 compound claim, no error, no warning**;
- the oracle (`evaluation/oracle.py`) always returns each sentence unsplit, so oracle runs of the
  full pipeline also verify v1-045 as one compound claim.

The prompt (`extract-claims-v1.txt` L17) asks for splitting; **nothing in code enforces it**. The
extraction evaluation only *counts* atomicity violations (`evaluation/extraction.py` L232).

## 5. Touchpoints for a new guard reason (Step 5)

`git grep -n "unsupported_quantity\|UNSUPPORTED_QUANTITY" HEAD`:

| File | Line | Kind |
|---|---|---|
| `services/verification/src/inkloom_verify/schemas.py` | 1183–1184 | enum `GuardRejectionReason` |
| `services/verification/schemas/verification_report.schema.json` | 576 | generated (`python -m inkloom_verify.json_schema`); drift fails a test |
| `services/verification/CONTRACTS.md` | 262 | documented reason list |
| `services/verification/PROMPTS.md` | 421 | support-checks table |
| `services/verification/EVAL.md` | 1120 | historical measurement (no change needed) |
| `services/verification/src/inkloom_verify/citation_guard.py` | 336 | producer |
| tests | `test_citation_guard.py`, `test_known_limitations.py`, `test_prompt_security.py`, `test_verification.py`, `test_verifier_prompt.py` | expectations |

**Backend and frontend:** no mapping or label table for guard reasons. `git grep "citation_guard"`
over `services/api/src` and `audit-ai-final` finds nothing. The backend has its own, separate
`IntegrityErrorCode` (`services/api/src/inkloom_api/engine/evidence_validator.py` L36) for its own
citation re-validation. **[VERIFY] resolved: none found.** A new engine reason is additive to the
engine's report schema only.

## 6. Tests and gates that pin today's behaviour (Step 6)

| What | Today (HEAD) | Expected to change? |
|---|---|---|
| `eval/baseline.json` "false-SUPPORTED (valid-quote, always SUPPORTED)" `<= 0.2909` | measured **16/55** | **Yes, down.** A correct guard fix refuses more wrongly supported records. The gate may then be tightened, never loosened. (The runbook's "≤ 16/55" matches.) |
| `tests/test_verification_eval.py` `test_false_supported_bound_under_adversarial_models` (valid-quote bound 14 of denominator 31; fabricator 0) | passes | **Yes, down or equal.** The numerator can only fall; the bound may be tightened. The fabricator bound stays 0. |
| `tests/test_known_limitations.py` + `evaluation/limitations.py` | 5 limitations pinned by 6 tests, plus a format test (PDF tables, English-only negation, number words, lexical retrieval, size limit) | **No** for A and B: neither is a pinned limitation. "Live model quality" text in `limitations.py` is a documentation question (see open questions), not a test. |
| `tests/test_citation_guard.py`, `test_verifier_prompt.py` | pin today's support checks | **No** existing expectation should change; new tests are added. |
| Oracle gate (`--verdicts oracle --check-baseline`) | every gold answer reaches its label | **No.** It must stay green: it proves a fix doesn't refuse correct answers. |

## 7. Failure paths, fix locations, do-not-touch, open questions

### Failure paths

| | File, function, line | Why | Reproduce |
|---|---|---|---|
| A (verification) | `citation_guard.py` `support_problems` L318, membership test L329–337, using `quantities` L268 | figures are compared as a set; their property is never read | `PYTHONPATH=<src> python r3_step01_repro.py <services/verification>` (section 3) |
| A (corrections) | `correction.py` `correction_issues` L131–136 (`mispaired`) | same set membership for a replacement figure | same script |
| B (verification) | `citation_guard.py` `support_problems` L318 (no check covers it) | no rule compares the claim's clauses with the evidence | same script (section 4) |
| B (policy) | `decision_policy.py` `review_reasons` L102 | compound handling only adds a review reason; 2 citations clear it | same script |
| B (extraction) | `extraction.py` `ClaimExtractor.extract` L297 | splitting is a prompt instruction, not enforced | `r3_step01_extract.py` |

### Proposed fix locations
1. **Guard, A:** bind each figure to the words around it in `citation_guard.py`, and refuse a claim
   whose figure the quotes give for another property. Narrow, per the runbook (step 03).
2. **Guard, B:** in `citation_guard.py`, refuse a SUPPORTED compound claim when one of its parts is
   absent from the cited passages (new reason). Optionally, **extraction atomicity check** in
   `extraction.py`: flag or split a claim that `looks_compound` sees as compound (step 04).
3. **Corrections:** reuse the step 03 and 04 checks inside `correction_issues` (step 05).

### Do-not-touch (work, strongly tested; a rewrite needs a written reason)
`retrieval.py`, `chunking.py`, `security.py`, `intent_lock.py`, `scope.py`, `providers/`
(privacy settings included), `prompts/*.txt` and `prompts.lock.json`, `eval/datasets.lock.json`
and the held-out records.

### Open questions for the team
1. **Contract:** a new `GuardRejectionReason` value is additive to
   `verification_report.schema.json` only (no backend or frontend consumer). Do Darsh and Chahit
   want to approve it before step 03/04, as step 02 requires?
2. **Backend review routing:** the backend routes on `verdict != SUPPORTED` only, so the engine's
   `compound_under_cited` reason never reaches the app (`limitations.py` "Backend review routing",
   suspected). Should the backend read `requires_human_review`?
3. **Three live-run accounts disagree.** EVAL.md L606 says no live report exists; EVAL.md L873–921
   documents a verifier-only free-model run (30/80 answered, gates failed); `limitations.py` L84–91
   cites a Gemini verifier-only run (recall 28/32) with evidence "EVAL.md", which has no Gemini
   section. Reports for all of them are in `eval/reports/` (`20261024T125130Z` and
   `20261024T172551Z`). Reconcile in step 07 before quoting any number.
4. **Extraction atomicity:** enforce in code (step 04 option) or accept that the guard is the only
   defence?

## State of the working tree (not audited above)

Uncommitted at the time of this audit, made before the runbook arrived, out of the runbook's order
(step 02 approval had not been given):

- steps 03/04/05 implementations in `citation_guard.py`, `decision_policy.py`, `correction.py`,
  `schemas.py`; new guard reason `unsupported_component` (schema +1 line); tests in
  `test_citation_guard.py` and new `test_correction_grounding.py`; REG-014/015/016; notes in
  `CONTRACTS.md`, `PROMPTS.md`, `EVAL.md`;
- `docs/round3/contracts.md` (a step 02 draft, not approved).

With those changes the same commands give 2003 passed / 3 xfailed, both gates exit 0, and the
valid-quote false-SUPPORTED gate measures 15/55. **Held-out exposure:** while building them, the
no-false-downgrade checks read the gold quotes of every SUPPORTED record in both datasets,
held-out included (`test_every_gold_quote_still_supports_its_supported_claim`), and the step 04
measurement listed which held-out records the new rule flags (v3-023). This must go into
`docs/round3/results/RUN_LEDGER.md` (step 07).
