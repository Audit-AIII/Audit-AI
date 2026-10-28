# Verification and evaluation contracts (draft)

**Status: DRAFT, UNAPPROVED.** Written on 2026-10-28 from the code at commit `1e416e5` (`main`),
on branch `krish/round3`. Sections 1–12 and 14 record what the code does today. Sections 15–21
are the Round 3 step 02 proposals (`docs/round3/krish/02-agree-contracts-and-metric-definitions.md`):
metric definitions, headline rule, payload shape, data path, risk mapping, the two new guard
reason codes, and the messages to Darsh and Chahit (drafted, **not sent**). Section 22 is the
acknowledgement log, empty until both reply in writing (STOP C).

**Nothing in this document has changed any payload, schema or production code.**

Every substantive statement carries one label:

- **VERIFIED**: confirmed in the source or tests at the cited path and line.
- **PROPOSAL**: a recommendation. Nobody has approved it.
- **UNRESOLVED**: needs the missing documents, a team decision or more investigation.

No approval from Darsh (backend) or Chahit (frontend) has been obtained for anything in this
document. Line numbers refer to commit `1e416e5`.

## 1. Purpose and scope

This document records the contracts that already exist between the verification engine
(`services/verification`, package `inkloom_verify`), the backend (`services/api`, package
`inkloom_api`) and the frontend (`audit-ai-final/frontend`) for two things:

1. **Claim verdicts**: what the engine decides about one claim, and how that decision reaches a
   stored finding and the review screen.
2. **Evaluation results**: how verification quality is measured, stored and shown on the Trust
   Scorecard.

Out of scope: brand-rule findings (`check_type: "rule"`), approval workflow, and changes to any
code. This document changes no behaviour.

## 2. Verified engine verdict contract

**VERIFIED.** The engine has exactly four verdicts
(`services/verification/src/inkloom_verify/schemas.py:851-855`):

| Verdict | Shape rules (`ClaimResult._check_verdict_shape`, `schemas.py:1264-1277` docstring and the validator below it) |
|---|---|
| `SUPPORTED` | At least one citation; no `error`. |
| `CONTRADICTED` | At least one citation; no `error`. The only verdict that may carry a `correction`. |
| `NOT_ENOUGH_EVIDENCE` | No citations, no correction, no error. `evidence` may still list the passages considered. The only verdict that may carry `safer_wording`. |
| `ERROR` | Requires an `error` (`ProcessingError`); no citations, no correction. |

**VERIFIED.** Other `ClaimResult` invariants (`schemas.py:1264-1345`):

- Every citation must quote, verbatim, a passage listed in `evidence`.
- When the citation guard downgrades a model answer, the verdict must be `NOT_ENOUGH_EVIDENCE`.
- `conflicting_sources` is derived from the citation guard (filled in when omitted, rejected when
  wrong). It is only ever true on a `NOT_ENOUGH_EVIDENCE` result.
- `evidence_strength` and `review_reasons` are derived by fixed rules, and a caller cannot
  inflate them.
- `requires_human_review` is true exactly when `review_reasons` is non-empty.

**VERIFIED.** The review floor (`floor_review_reasons`, `schemas.py:1138-1146`):

- `CONTRADICTED` → `contradicted`
- `NOT_ENOUGH_EVIDENCE` → `not_enough_evidence`
- `ERROR` → `error`
- `SUPPORTED` on weak evidence → `weak_evidence`
- `SUPPORTED` otherwise → no reason

A `DecisionPolicy` may add `below_policy_strength` or `compound_under_cited`, and only to
`SUPPORTED` claims. It can route more claims to review, never fewer (`ClaimReviewReason`
docstring, `schemas.py:1106-1112`).

**VERIFIED.** `NOT_ENOUGH_EVIDENCE` deliberately covers three situations:

- no evidence found;
- conflicting references;
- an answer the citation guard rejected.

A missing fact is never reported as false (`schemas.py:1108-1110`, comment on
`NOT_ENOUGH_EVIDENCE`).

## 3. Backend status mapping

**VERIFIED.** The backend maps each engine verdict to a stored finding in
`services/api/src/inkloom_api/engine/pipeline.py`:

| Engine verdict | `verification_status` (`:98-103`) | `category` (`:110-115`) | `severity` (`:104-109`) | Evidence relation (`:116-119`) |
|---|---|---|---|---|
| `SUPPORTED` | `supported` | `supported_claim` | `low` | `supports` |
| `CONTRADICTED` | `contradicted` | `contradicted_claim` | `high` | `contradicts` |
| `NOT_ENOUGH_EVIDENCE` | `unverified` | `unsupported_claim` | `medium` | none stored |
| `ERROR` | `unverified` | `engine_error` | `medium` | none stored |

**VERIFIED.** Adjustments in `_write_finding` (`pipeline.py:459-552`):

- **Backend citation check:** a `SUPPORTED` or `CONTRADICTED` result whose citations fail the
  backend's own validation (`validate_all`) is downgraded to `NOT_ENOUGH_EVIDENCE` before
  mapping. Its explanation is replaced, and its suggestion and evidence links are dropped
  (`:494-505`).
- **Conflicting sources:** `NOT_ENOUGH_EVIDENCE` with `conflicting_sources = true` is stored as
  `conflicting_sources`, not `unverified` (`:517-522`).
- **Suggestions:**
  - `suggested_correction` comes only from a `CONTRADICTED` result's correction.
  - `safer_wording` comes only for `NOT_ENOUGH_EVIDENCE`, and must pass `softening_issues`
    (`:475-489`).
  - Either suggestion is removed if it would break an Intent-lock phrase (`:509-512`).
- **Human review:** `requires_human_review = verdict is not SUPPORTED or result.requires_human_review`
  (`:513`).
- **`review_reasons`:**
  - normally the engine's reasons;
  - `[not_enough_evidence]` if the backend downgraded the claim;
  - `[error]` if the claim needs review but has no reason (`_review_reasons`, `:555-564`).

**VERIFIED. These mappings lose information:**

1. **`ERROR` and `NOT_ENOUGH_EVIDENCE` share `verification_status: "unverified"`.**
   - **API:** they differ only by `category` (`engine_error` vs `unsupported_claim`) and
     `review_reasons`.
   - **Frontend:** the review screen's verdict chip reads only `verification_status`, so both
     show "Not proven yet" (`audit-ai-final/frontend/components/app/reviewLabels.ts:7-23`).
   - **Misleading text:** for a claim finding with no evidence, the detail panel says "None of
     your approved documents cover this", even when the claim was never checked because of an
     engine error (`audit-ai-final/frontend/app/app/review/ReviewResult.tsx:423`).
   - **Where it does show:** only the Insights page labels `engine_error` separately ("Could not
     be checked", `app/app/insights/Insights.tsx:34`).
2. **The engine's error detail is lost.** The engine's `error.code` and `error.stage` are not
   stored on the finding. Only `error.message` becomes `explanation` (`pipeline.py:472`).
3. **Evidence is dropped for unverified claims.** For `NOT_ENOUGH_EVIDENCE` and `ERROR`, the
   passages the engine considered are not stored: no `EvidenceLink` rows (`pipeline.py:536-538`).
4. **The model's verdict is discarded.** When the citation guard downgrades an answer, the
   finding records only the final verdict.

**VERIFIED.** The frontend's `VerificationStatus` type is
`"supported" | "contradicted" | "unverified" | "conflicting_sources" | "not_applicable"`, left
open to unknown strings (`audit-ai-final/frontend/lib/api/types.ts:81-83`).
`reviewLabels.verdict()` renders an unknown value as a readable "unverified"-toned chip
(`reviewLabels.ts:20-21`).

## 4. Engine `evaluation-summary-v1` schema

**VERIFIED.** The summary is defined in
`services/verification/src/inkloom_verify/evaluation/summary.py`. Its JSON Schema is in
`services/verification/schemas/evaluation_summary.schema.json`.

- **Producer:** `eval/run_eval.py`, once per run. It's written next to the report as
  `eval/reports/<stem>.summary.json` (`summary.py:1-11`; `build_summary` called at
  `eval/run_eval.py:774`). It is a file on disk, not a database row.
- **Three states**, all with `contract: "evaluation-summary-v1"`:
  - `available`: `EvaluationSummary`, `summary.py:113-135`.
  - `none`: `NoEvaluation`, `:138-144`.
  - `incomplete`: `IncompleteEvaluation`, `:147-156`, written when a run stops
    (`run_eval.py:777-800`).
- **`available` fields:**
  - `report_id`, `generated_at`, `outcome`;
  - `source`: verdict source, kind, `is_model_quality`, `benchmark: true`,
    `production_statistics: false`, commit and engine version;
  - `dataset`, `model`, `prompt_versions`, `retrieval`, `decision_policy`, `counts`;
  - `metrics`: exactly 8 `MetricOut`, each with `key`, `label`, `explanation`, `display`,
    `value`, `numerator`, `denominator` and `unavailable_reason`;
  - `confusion`, `review`, `corrections`, `gates`;
  - `cases`: at most 6 real records;
  - `limitations`, `unavailable`, `stale`, `stale_reason`.
- **The 8 metrics:** keys and labels come from `report.METRICS`
  (`evaluation/report.py:38-...`). Values come from `required_metrics.compute`, the "eight
  metrics EVAL.md requires" (`evaluation/required_metrics.py:1-40`).
- **Pipeline:** `run_eval.py` defaults to `--pipeline full`. That runs `verify_request` per
  record: extraction, retrieval, verification, citation guard, correction and the human-review
  decision (`run_eval.py:16-21`, default at `:655-657`). `--pipeline verifier` runs retrieval, the
  verifier and the guard only. The oracle source requires `full` (`:694`).

**VERIFIED. Gaps in the summary:**

- **Pipeline mode is missing.** The report records it (`run["pipeline"]`, `run_eval.py:415`), but
  `EvaluationSummary` has no field that names it. Readers can only infer it from `review` and
  `cases`.
- **The docstring is out of date.** `summary.py:4-5` says "the backend serves the latest one
  (`GET /api/evaluations/latest`)". The backend does not: that route serves its own stored run
  (section 5). The frontend comment agrees that the summary is "unused by the backend today"
  (`audit-ai-final/frontend/lib/additions/analytics.ts:61`).

## 5. Backend `EvaluationOut` schema

**VERIFIED.** The producer is `run_evaluation` in
`services/api/src/inkloom_api/evaluation_runner.py:204-260`. It is called by
`POST /api/evaluations` (`routers/evaluations.py:166`).

**Stored.** An `EvaluationRun` database row (`models/evaluation.py:26-38`) holds:

- `status` (`completed`, or `partial` if any claim got `ERROR`), `ran_at`,
  `engine_prompt_version`, `dataset_version`, `sample_size` and `limits_note`;
- `metrics` (JSONB): `catch_rate` and `false_positive_rate` as `{numerator, denominator, value}`,
  plus `per_check`, `by_split`, `coverage`, `latency_ms_p50`, `provider_failure_rate`,
  `verdict_accuracy`, `model_ids`, `calls_used` and `definitions` (`evaluation_runner.py:234-247`).

**Served as `EvaluationOut`** (`routers/evaluations.py:70-112`, built by `from_model`):

| Field | Type | Source |
|---|---|---|
| `catch_rate` | float \| null | `metrics.catch_rate.value`; numerator and denominator are **not** exposed |
| `false_positive_rate` | float \| null | `metrics.false_positive_rate.value`; numerator and denominator are **not** exposed |
| `per_check[]` | `{check, catch_rate, false_positive_rate, n}` | `metrics.per_check`; rates as values only |
| `sample_size` | int | column |
| `run_at` | datetime | `ran_at` column |
| `id`, `status`, `engine_prompt_version`, `dataset_version`, `limits_note` | | columns |
| `latency_ms_p50`, `provider_failure_rate` | float \| null | `metrics` |
| `coverage` | str | `metrics.coverage`; defaults to `"verifier_only"` for old rows |
| `by_split` | `{split: {n, catch_rate: Ratio, false_positive_rate: Ratio}}` \| null | `metrics.by_split`; null for old rows |
| `provider_mode` | `"live" \| "scripted" \| "mixed"` \| null | derived from `metrics.model_ids` (`evaluation_runner.py:173`) |

**VERIFIED.** Stored but never served: `verdict_accuracy`, `model_ids` (served only as
`provider_mode`), `calls_used`, `definitions`, and the headline rates' numerators and
denominators.

**VERIFIED.** The comment at `routers/evaluations.py:71-73` makes this shape a hard contract:
"Additive changes only, and never a `contract` key". The frontend uses the absence of a
`contract` key to tell this shape from `evaluation-summary-v1`.

## 6. Evaluation pipeline differences

| | Backend `EvaluationOut` | Engine `evaluation-summary-v1` |
|---|---|---|
| Predictor | `EngineVerifierPredictor`: BM25 retrieval, the verifier and the citation guard on the labelled claim (`evaluation_runner.py:218`; `runner.py:125-127`). **VERIFIED** | `PipelinePredictor` (`verify_request`) by default; `--pipeline verifier` is optional (`run_eval.py:395-401`). **VERIFIED** |
| Coverage | Always `verifier_only` (`evaluation_runner.py:56-58`, `:240`). **VERIFIED** | Full pipeline by default; the mode isn't stated in the summary (section 4). **VERIFIED** |
| Not covered | Extraction, correction, decision policy, the backend's own citation re-validation and the human-review decision (`evaluation_runner.py:21-26`). **VERIFIED** | The backend's own citation re-validation, which only the backend does. **VERIFIED** (the engine has no access to backend corpus records) |
| Provider | The backend's fallback chain, wrapped in `BudgetedProvider` (`evaluation_runner.py:208-215`). **VERIFIED** | Oracle, abstain, live OpenRouter, replay or saved predictions (`summary.py:29-36`). **VERIFIED** |
| Scope | Per account; stored in Postgres. **VERIFIED** | Global; files in `eval/reports/` on the machine that ran it. **VERIFIED** |
| Run refused | More than `eval_max_provider_failure_rate` (default 20%) of claims got `ERROR`: 409, nothing stored (`routers/evaluations.py:198-219`). **VERIFIED** | An unfinished run writes an `incomplete` summary (`run_eval.py:777-800`). **VERIFIED** |
| Missing prediction | Predictor exception → `ERROR` (`evaluation_runner.py:223-227`). **VERIFIED** | A missing prediction is scored as `ERROR` (`runner.py:505-508`; `required_metrics.py:17-18`). **VERIFIED** |

**VERIFIED.** The two objects are **not interchangeable**:

- They measure different pipelines.
- They share field names with different definitions (section 8).
- They are stored in different places.

## 7. Existing metric definitions

All metrics below are computed from a confusion matrix whose rows are gold labels (`SUPPORTED`,
`CONTRADICTED`, `NOT_ENOUGH_EVIDENCE`) and whose columns are predictions, including `ERROR`
(`metrics.py:72-84`; `GOLD_CLASSES`/`PREDICTED_CLASSES` at `:19-24`). A rate with a zero
denominator has `value: null`, never 0 or 1 (`metrics.ratio`, `metrics.py:43-50`). Every row
below is **VERIFIED** at the cited lines.

### Trust Scorecard candidates (engine `metrics.py`, served by the backend)

Here "flagged" means `CONTRADICTED` or `NOT_ENOUGH_EVIDENCE` (`metrics.py:142-145`). The engine
labels these "Candidate definitions only; not yet agreed with the Trust Scorecard owner"
(`runner.py:370-375`, `metrics.py:144`).

| Metric | Numerator | Denominator | Eligible | Excluded | Source |
|---|---|---|---|---|---|
| `catch_rate` | records labelled `CONTRADICTED` or `NOT_ENOUGH_EVIDENCE` and predicted `CONTRADICTED` or `NOT_ENOUGH_EVIDENCE` | all records labelled `CONTRADICTED` or `NOT_ENOUGH_EVIDENCE` | those records | records labelled `SUPPORTED`. `ERROR` stays in the denominator and is not counted as caught | `metrics.py:148-152` |
| `false_positive_rate` (**FPR-A**) | records labelled `SUPPORTED` and predicted `CONTRADICTED` or `NOT_ENOUGH_EVIDENCE` | all records labelled `SUPPORTED` | records labelled `SUPPORTED` | other labels. `ERROR` stays in the denominator and is not counted as flagged | `metrics.py:155-158` |
| `provider_failure_rate` | records predicted `ERROR` | all records | all | none | `evaluation_runner.py:242` (rounded to 4 places) |
| `per_check[]` | the same two rates for the subset with each `check` category | | | | `evaluation_runner.py:121-146` |
| `by_split.{dev,heldout}` | the same two rates per split, with numerator and denominator | | | | `evaluation_runner.py:148-170` |
| `latency_ms_p50` | median per-record prediction time (ms) | | | | `evaluation_runner.py:241` |

**Aggregation:** micro, one count per record, pooled over the whole dataset (dev and held-out
together) for the headline numbers, and separately per split in `by_split`.

### The eight required metrics (engine `required_metrics.py`, in `summary.json`)

Here the positive class is `CONTRADICTED` (`required_metrics.py:9-18`, `POSITIVE` at `:73`):

- **TP:** labelled `CONTRADICTED`, predicted `CONTRADICTED`.
- **FP:** labelled `SUPPORTED` or `NOT_ENOUGH_EVIDENCE`, predicted `CONTRADICTED`.
- **FN:** labelled `CONTRADICTED`, predicted anything else, including `ERROR` and missing.
- **TN:** labelled `SUPPORTED` or `NOT_ENOUGH_EVIDENCE`, predicted anything except `CONTRADICTED`,
  including `ERROR` and missing.

| Metric | Definition | Source |
|---|---|---|
| `contradicted_precision` | TP / (TP + FP); unavailable if `CONTRADICTED` was never predicted | `required_metrics.py:20`, `:257-259` |
| `contradicted_recall` | TP / (TP + FN) | `:21`, `:260-262` |
| `false_positive_rate` (**FPR-B**) | FP / (FP + TN) | `:22`, `:263-269` |
| `false_negative_rate` | FN / (TP + FN) | `:23`, `:270-272` |
| `citation_validity` | valid citations / all citations | `:24-30` |
| `retrieval_recall@5` | records whose gold evidence overlaps a top-5 passage / records with gold evidence | `:31-34` |
| human-review share | records routed to a person / records with a pipeline outcome (`--pipeline full` only) | `:35-37` |
| correction traceability | traceable proposals / proposed corrections | `:38-40` |

`ERROR` predictions are reported separately by cause, with how many landed in FN and how many
in TN (`required_metrics.py:113-116`, `:208-217`). **Aggregation:** micro over the evaluated
records.

**VERIFIED.** `run_eval.py` computes the eight metrics twice from the same predictions: pooled
over all records (`report["required_metrics"]`, `run_eval.py:542`) and per split
(`report["required_metrics_by_split"]`, `:552-557`). The code comment there says the held-out
numbers are the ones to quote. `summary.json` takes the **pooled** set (`summary.py:244`).

## 8. False-positive-rate discrepancy

**VERIFIED.** Two different metrics are both named `false_positive_rate`. Both are implemented in
the engine:

| | FPR-A (`metrics.false_positive_rate`) | FPR-B (`required_metrics` `false_positive_rate`) |
|---|---|---|
| Question answered | Of the claims that are true, how many did we flag as a problem? | Of the claims that are not contradicted, how many did we wrongly call contradicted? |
| Positive (flagged) prediction | `CONTRADICTED` **or** `NOT_ENOUGH_EVIDENCE` | `CONTRADICTED` only |
| Denominator | records labelled `SUPPORTED` | records labelled `SUPPORTED` **or** `NOT_ENOUGH_EVIDENCE` |
| `ERROR` | in the denominator, not flagged | in the denominator, counted as TN |
| Where it appears | backend `EvaluationOut.false_positive_rate`, `per_check`, `by_split`; the Scorecard "run" view | `evaluation-summary-v1` `metrics[]`; the Scorecard "summary" view and the Markdown report |
| Pipeline | verifier only (backend runner) | full pipeline by default (`run_eval.py`) |

**VERIFIED worked example.** I computed this example with the real functions
(`metrics.confusion_matrix` and `metrics.false_positive_rate`, and `required_metrics.compute` on
ten real dev records with assigned predictions). It is an illustration, not a measured result.

| Gold label | Predictions |
|---|---|
| `SUPPORTED` (4) | `SUPPORTED`, `SUPPORTED`, `NOT_ENOUGH_EVIDENCE`, `CONTRADICTED` |
| `NOT_ENOUGH_EVIDENCE` (2) | `NOT_ENOUGH_EVIDENCE`, `CONTRADICTED` |
| `CONTRADICTED` (4) | `CONTRADICTED`, `CONTRADICTED`, `CONTRADICTED`, `ERROR` |

Results:

- FPR-A = 2 / 4 = **50.0%**: both non-`SUPPORTED` predictions on true claims count.
- FPR-B = 2 / 6 = **33.3%**: only the two `CONTRADICTED` predictions on the six non-contradicted
  records count.
- `catch_rate` = 5 / 6 = 83.3%.
- `contradicted_recall` = 3 / 4 = 75.0%.

The same predictions give two different "false-positive rates". Neither definition is wrong:
they answer different questions.

**VERIFIED. Existing guards against confusing the two:**

- The Scorecard renders either a backend run (`RunReport.tsx`) or a summary (`Scorecard.tsx`),
  never both. Which one it renders depends on whether the response has a `contract` key
  (`analytics.ts:59-62`; `evaluationRun.ts:62`).
- `RunReport.tsx:47-49` explains FPR-A in words ("claims labelled supported that it flagged
  anyway").

**VERIFIED. Remaining confusion risks:**

- Both views use the label "False-positive rate".
- The headline card's caption reads "Sample: N labelled claims" (`RunReport.tsx:45`). That is
  the whole sample, not FPR-A's denominator, which is only the claims labelled `SUPPORTED`.

**This draft does not reconcile the two definitions.** See PROPOSAL 1 in section 12.

## 9. API routes and consumers

**VERIFIED.**

| Route | Behaviour | Source |
|---|---|---|
| `GET /api/evaluations/latest` | 200 with `EvaluationOut` for the account's latest stored run; **404** `no evaluation has been run yet` | `routers/evaluations.py:114-127` |
| `POST /api/evaluations` | Synchronous run, then **201** `EvaluationOut` | `:166` |
| | **409** when no provider is configured, or the dataset is unavailable or changed | `:191`, `:196` |
| | **409** "could not answer N of M…" when the failure rate is over the limit; nothing stored, but audited as `evaluation.discarded` | `:198-219` |
| | **429** when called within 10 minutes of the previous run, or while one is already running; `Retry-After` header and `error.retry_after` | `:133-163`, `:176-181` |

**VERIFIED.** Nothing in `services/api` serves `evaluation-summary-v1`. The engine's own HTTP
API (`POST /v1/verify`, `inkloom_verify/api.py`) is separate from evaluation.

## 10. Frontend Scorecard data contract

**VERIFIED. Data flow:**

1. `latestEvaluation()` (`audit-ai-final/frontend/lib/additions/analytics.ts:67-77`) calls
   `GET /api/evaluations/latest`.
2. `parseLatest` (`:59-62`) chooses a parser:
   - `looksLikeRunEvaluation` (has `catch_rate` and `per_check`, and no `contract` key;
     `evaluationRun.ts:62`) → `parseRunEvaluation` → `runEvaluationProblem`.
   - Otherwise `parseEvaluation` (`analytics.ts:165-...`), which accepts only
     `contract: "evaluation-summary-v1"`.
3. A **404** becomes a synthetic `{contract: "evaluation-summary-v1", state: "none"}`, shown as
   "no evaluation yet" (`analytics.ts:71-73`).
4. `runEvaluation()` (`:65`) calls `POST /api/evaluations` and parses the response with
   `parseRunEvaluation`.

**VERIFIED. `runEvaluationProblem`** (`evaluationRun.ts:41-59`) is strict: one field of the wrong
type rejects the whole response, and no number is defaulted.

- **Required numbers or null:** `catch_rate`, `false_positive_rate`, `latency_ms_p50`,
  `provider_failure_rate`.
- **Required list:** `per_check[]`, each item `{check: string, catch_rate, false_positive_rate:
  number | null, n: number}`.
- **Required number:** `sample_size`.
- **Required text:** `run_at`, `id`, `status`, `dataset_version`, `limits_note`, `coverage`.
- **Text or null:** `engine_prompt_version`, `provider_mode`.
- **Object or null:** `by_split`; each split needs `n` plus `catch_rate` and
  `false_positive_rate` as `{numerator, denominator: number, value: number | null}`.

**VERIFIED. Where the fields are displayed** (`RunReport.tsx`):

- `catch_rate` and `false_positive_rate` as percentages (`formatRate`, `evaluationRun.ts:68-72`),
  the "Catch rate" and "False-positive rate" cards (`:44-45`).
- `by_split` rows as "X of Y" with dev and held-out labels (`:12`, `:56-80`).
- `per_check` as a table (`:91-111`).
- `status === "partial"` explained in words (`:125`).
- `coverage`, `limits_note` and `provider_mode` text (`:24-34`).

**VERIFIED. Error handling** (`Scorecard.tsx:51-60`):

- 429 → wait for `retryAt`.
- 409 "could not answer" → failed, and counts toward the interval.
- Other 409s → failed, and a retry is allowed right away.

**UNRESOLVED.** I did not check, field by field, which `EvaluationOut` fields `RunReport.tsx`
never displays (for example `engine_prompt_version`, `dataset_version` and `latency_ms_p50`).
Finding out needs a full read of `RunReport.tsx:113-144`.

## 11. Compatibility risks

All **VERIFIED** unless marked otherwise.

1. **Same name, different metric.** `false_positive_rate` means FPR-A in `EvaluationOut` and
   FPR-B in `evaluation-summary-v1` (section 8). Any code or person moving numbers between the
   two will compare unlike things.
2. **A `contract` key would change the parser.** Adding a `contract` key to `EvaluationOut`
   would send it down the `evaluation-summary-v1` parser, which would reject it
   (`evaluationRun.ts:62`, `analytics.ts:165-167`). The backend comment forbids this key
   (`routers/evaluations.py:71-73`).
3. **The frontend parser rejects type changes.** A non-additive change to `EvaluationOut`, such
   as turning `catch_rate` into a `Ratio` object, fails `runEvaluationProblem` and the page shows
   an error. Adding a new field is safe, because the parser ignores unknown keys.
4. **Missing pipeline mode.** `evaluation-summary-v1` doesn't record the pipeline mode, so a
   verifier-only summary and a full-pipeline summary look alike.
5. **Out-of-date docstring.** `summary.py:4-5` describes a backend behaviour that doesn't exist.
6. **`ERROR` lowers the catch rate without being flagged.** Combined with the 20% discard
   threshold, a stored run can still have up to 20% `ERROR` predictions. They lower the catch
   rate and FPR-A (both keep `ERROR` in the denominator), and the run is labelled only
   `status: "partial"`.
7. **`ERROR` looks like "no evidence" on the review screen.** The review screen shows both as
   "Not proven yet", with text saying the documents don't cover the claim (section 3).
8. **The headline mixes splits.** Headline rates pool dev and held-out. The API documentation
   (`services/api/API.md`, Trust Scorecard section) says held-out is the figure to quote, but
   the headline cards show the pooled value.

## 12. Proposed metric decisions requiring approval

These are **PROPOSALS**. None is approved. Owners: Krish (engine), Darsh (backend), Chahit
(frontend).

1. **PROPOSAL 1: rename instead of choosing one false-positive rate.** Keep both metrics, with
   distinct names in any new field or label:
   - FPR-A as `flagged_supported_rate` ("true claims flagged as a problem").
   - FPR-B as `contradicted_false_positive_rate` ("non-contradicted claims called contradicted").

   Leave the existing `false_positive_rate` fields unchanged for compatibility. Any new field
   must be additive (risk 2 and 3). *Needs:* Krish, Darsh and Chahit.
2. **PROPOSAL 2: say in the UI which definition is shown.** Add a short definition next to each
   "False-positive rate" label, in both Scorecard views. Change the headline caption so it shows
   that metric's own denominator, not `sample_size`. Requires exposing the headline
   numerator and denominator in `EvaluationOut`; additive fields such as
   `catch_rate_ratio` would do it. *Needs:* Chahit and Darsh.
3. **PROPOSAL 3: add `pipeline` to `evaluation-summary-v1`** (`"full" | "verifier" | null`), as an
   additive field, and fix the docstring at `summary.py:4-5`. *Needs:* Krish, and Chahit for the
   parser.
4. **PROPOSAL 4: quote held-out figures first.** Make `by_split.heldout` the primary figure on the
   Scorecard, with the pooled number as context, as API.md already recommends. *Needs:* Chahit,
   and a product decision.
5. **PROPOSAL 5: tell `engine_error` apart from unverified on the review screen.** Branch on
   `category === "engine_error"` (or on `review_reasons` containing `error`) instead of showing
   the "documents don't cover this" note. *Needs:* Chahit. No API change.
6. **PROPOSAL 6: say how `ERROR` is treated wherever a rate is shown.** Every displayed rate
   should state that claims without an answer stay in the denominator. *Needs:* Chahit.

## 13. Status of earlier open points

- **Runbook:** now in the repo (`docs/round3/krish/`). This document follows step 02.
- **Phase 1 audit:** done (`docs/round3/krish/pipeline-audit.md`); `v1-036` and `v1-045`
  reproduced at `1e416e5`.
- **"Not yet agreed with the Trust Scorecard owner"** (`runner.py:374`, `metrics.py:144`): still
  true. Section 15 is the proposal that would end it.
- **Verifier-only or full pipeline:** the proposal is full pipeline (section 17, `coverage`).
- **Backend review routing.** `evaluation/limitations.py` ("Backend review routing", status
  `suspected`) says the backend routes on `verdict != SUPPORTED` only and ignores the engine's
  decision policy. **VERIFIED: that is out of date.** The backend applies the engine's policy
  (`services/api/src/inkloom_api/engine/pipeline.py:257`, `_with_decision_policy` at `:313`); a
  finding needs review when its verdict isn't SUPPORTED **or** the engine says so (`:513`); any
  such finding sets the review to `NEEDS_HUMAN_REVIEW` (`:261-264`). What the backend does **not**
  have is per-finding risk tiers (section 19). Correcting `limitations.py` is a code change for a
  later step, not this one.

## 14. Tests and verification evidence

**VERIFIED.** No code was changed. The tests below were run on commit `1e416e5`.

| Area | Tests |
|---|---|
| Verdict contract | `services/verification/tests/test_claim_result.py`, `test_api_contract.py`, `test_contract_v02.py`, `test_contract_e2e.py` |
| Metrics | `test_eval_metrics.py`, `test_required_metrics.py`, `test_eval_runner.py`, `test_eval_failure_handling.py` |
| Summary and report | `test_report.py`, `test_report_generation.py`, `test_run_eval.py`, `test_run_eval_pipeline.py` |
| Frontend consumption | `test_frontend_consumption.py` |
| Backend | `services/api/tests/test_evaluations.py`, `test_eval_retry_history.py`, `test_engine_integration.py`, `test_unverified_suggestions.py` |
| Frontend parser | `audit-ai-final/frontend/qa/unit/evaluation-run.test.mts` |

Results are recorded in the review report that accompanies this draft. The worked example in
section 8 was computed with the engine's own functions in a throwaway script; no file was
written for it.

---

# Round 3 step 02 proposals (DRAFT, UNAPPROVED)

Everything below is a **PROPOSAL** unless marked VERIFIED. Owners: Krish (engine, metrics),
Darsh (backend, routing), Chahit (frontend, Scorecard). Nothing here has been sent or approved.

## 15. Metric definitions

**PROPOSAL.** The plan's wording mapped onto the repo's labels:

| Term | Definition |
|---|---|
| **Problematic claim** | a record labelled `CONTRADICTED` or `NOT_ENOUGH_EVIDENCE` |
| **Flagged** | the engine's final record verdict is `CONTRADICTED` or `NOT_ENOUGH_EVIDENCE` (what the product shows as a problem) |
| **Catch rate** | problematic claims that were flagged ÷ all problematic claims |
| **False-positive rate** | claims labelled `SUPPORTED` that were flagged ÷ all `SUPPORTED` claims (this is FPR-A, section 8) |
| `ERROR` / provider failure | counts as **not flagged**: a miss on a problematic claim, never a false positive. Reported separately as `provider_failure_rate`. A run with any `ERROR` is `partial`. |
| Zero denominator | `value: null`, shown as "n/a", never 0% or 100% |

**VERIFIED:** catch rate and false-positive rate as defined above are exactly what the engine
already computes (`metrics.py:148-158`) and the backend already stores (section 7). Adopting them
changes no code.

**Companion numbers**, so the broad catch rate can't hide a weak verifier:
- **CONTRADICTED recall:** labelled CONTRADICTED and predicted CONTRADICTED ÷ labelled CONTRADICTED
  (already in `required_metrics`).
- **Wrong approvals:** records predicted SUPPORTED whose label is not SUPPORTED, as a count per
  label (already in the confusion matrix).

**Every published rate carries:** numerator / denominator, `n`, split, model and configuration,
dataset hash, date and limitations.

### Resolving the "false-positive rate" name collision

**PROPOSAL (smallest change):** keep every JSON key; change only the **display text** of FPR-B.

- **Change:** the label of required metric 3 from "False-positive rate" to
  **"False-CONTRADICTED rate"**, in `evaluation/report.py:51` (`METRICS`, which becomes
  `metrics[].label` in `summary.json`) and `required_metrics.py:481` (Markdown table). The
  summary view of the Scorecard renders that label from the data (`analytics.ts:83`), so the
  frontend needs no change. EVAL.md's metric table (L446) gets the same wording.
- **Unchanged:** the key `false_positive_rate` in both payloads, and FPR-A's label "False-positive
  rate" on the backend run view.
- This replaces the key renames in PROPOSAL 1 (section 12): renaming keys is not needed to stop
  two numbers sharing a name on screen.

**VERIFIED consumers of `false_positive_rate`** (`git grep`, 2026-10-28; none is renamed):

| Area | Files | Which metric |
|---|---|---|
| Engine | `evaluation/metrics.py`, `runner.py`, `__main__.py`, `required_metrics.py`, `report.py`; tests `test_eval_metrics.py`, `test_eval_runner.py`, `test_required_metrics.py`, `test_report_generation.py`; fixture `eval/fixtures/required_metrics/SAMPLE_REPORT.json` | FPR-A in `metrics`/`runner`; FPR-B in `required_metrics`/`report` |
| Backend | `evaluation_runner.py`, `routers/evaluations.py`, `API.md`, `tests/test_evaluations.py` | FPR-A |
| Frontend | `lib/additions/evaluationRun.ts`, `app/app/scorecard/RunReport.tsx`, `qa/unit/evaluation-run.test.mts`, `qa/fixtures/evaluation-run.api-example.json` | FPR-A |
| Docs | `contract/README.md:139` | FPR-A |

## 16. Headline rule

**PROPOSAL:** **The headline is the held-out split only.** Dev records were used to tune the
engine, so pooled numbers are optimistic (EVAL.md; `API.md` Trust Scorecard section; the comment
at `run_eval.py:549-551`). The payload already has `by_split.heldout` (backend) and
`required_metrics_by_split` (engine report); the contract makes held-out the **named** headline
instead of something the UI has to pick. Pooled and dev numbers may be shown as context, labelled,
never as the headline.

Held-out exposure is recorded in `docs/round3/results/RUN_LEDGER.md`, and fresh held-out records
are reported separately from previously viewed ones (step 06).

## 17. Scorecard payload (additive only)

**VERIFIED constraint:** `EvaluationOut` takes additive fields only and never a `contract` key
(`services/api/API.md` ~L520, `routers/evaluations.py:71-73`); the frontend parser ignores unknown
keys (section 11, risk 3).

**PROPOSAL.** New fields on top of `EvaluationOut`; names are proposals to align with Darsh.

```json
{
  "coverage": "full_pipeline",
  "headline": {
    "split": "heldout",
    "n": 0,
    "catch_rate":          {"numerator": 0, "denominator": 0, "value": null},
    "false_positive_rate": {"numerator": 0, "denominator": 0, "value": null},
    "contradicted_recall": {"numerator": 0, "denominator": 0, "value": null}
  },
  "run": {
    "run_id": "…", "created_at": "…", "provider_mode": "live",
    "models": ["<model id>"],
    "prompt_versions": {"extract_claims": "…", "verify_claim": "…", "correct_claim": "…"},
    "retrieval": {"strategy": "…", "top_k": 5},
    "decision_policy_version": "decision-policy-v1",
    "dataset": {"path": "eval/dataset.jsonl", "sha256": "…", "records": 0, "human_reviewed": 0},
    "git_commit": "…"
  },
  "stages": {"extraction": {}, "retrieval": {}, "verification": {}, "corrections": {}},
  "guard_regressions": {
    "numeric_binding": {"passed": 0, "total": 0},
    "compound_claims": {"passed": 0, "total": 0}
  },
  "limitations": [{"topic": "…", "status": "measured|suspected|unsupported|not_implemented", "finding": "…"}]
}
```

- **This is a shape, not data.** The zeros and nulls are placeholders; a fixture with them must
  never be rendered as a result (the frontend already labels scripted vs live; keep that).
- **Already exists, reused, not duplicated:** `coverage` (today always `"verifier_only"`;
  `"full_pipeline"` is reserved in `API.md`), `provider_failure_rate`, `by_split`,
  `provider_mode`.
- **Reuse instead of reinventing:** `evaluation/summary.py` (`EvaluationSummary`,
  `evaluation-summary-v1`), `schemas/evaluation_summary.schema.json`, `evaluation/limitations.py`,
  and the fixture `audit-ai-final/frontend/qa/fixtures/evaluation-run.api-example.json`.
- `headline.false_positive_rate` is FPR-A, the same metric as the existing top-level field.

## 18. Data path (decision for Darsh and Krish)

| Option | How | Pros | Cons |
|---|---|---|---|
| **1. CLI is the source of truth (recommended)** | Krish runs `eval/run_eval.py`; the engine writes `<timestamp>.summary.json`; the backend ingests or serves that file | reproducible by one command; no cost or timeout in the demo; the published artifact is the exact artifact | needs an ingest/serve path for the file (none today: section 9) |
| 2. Backend runs the full pipeline | swap the predictor in `evaluation_runner.py` to the engine's `PipelinePredictor`; set `coverage: "full_pipeline"` | the "run evaluation" button re-runs live | the POST already takes ~1–4 min verifier-only; full pipeline is slower; 1 run / 10 min / user; costs money per click; **[VERIFY]** the demo host's request timeout |

**PROPOSAL: option 1.** Either way, **no metric is computed outside the runner**: the page shows
the runner's numbers and never recomputes them.

## 19. Risk mapping for routing (for Darsh)

**VERIFIED today:** per claim the engine emits `verdict`, `requires_human_review`,
`review_reasons` (`contradicted`, `not_enough_evidence`, `error`, `weak_evidence`,
`below_policy_strength`, `compound_under_cited`) and `evidence_strength`. The backend applies the
engine's decision policy and routes a whole review to `NEEDS_HUMAN_REVIEW` if any finding needs
review (section 13). It stores `severity` per verdict (section 3) but has no risk tier that uses
`review_reasons`.

**PROPOSAL:**

| Engine signal | Proposed routing input |
|---|---|
| verdict `CONTRADICTED` | high risk → reviewer queue |
| verdict `NOT_ENOUGH_EVIDENCE` or `ERROR` | medium → reviewer queue |
| `SUPPORTED` with any `review_reasons` | low → reviewer queue (the policy says a person should look) |
| `SUPPORTED`, no `review_reasons` | clean → approver only |

Context: `DECISIONS.md` (24 Oct) decided single-user accounts, so multi-user routing is "deferred,
not built" in the repo while Round 3 commits to it. That is Darsh's conversation.

## 20. Two new guard reason codes (proposal for steps 03 and 04)

**PROPOSAL.** Two additive values of `GuardRejectionReason`, arriving in reports as
`citation_guard.rejected[].reason` and in the generated `verification_report.schema.json`:

| Code | Meaning | Why a new code, not `unsupported_quantity` |
|---|---|---|
| `property_mismatch` | a figure in the claim is attached to a different property in the quotes | the report then says *why* a present figure was refused, which `unsupported_quantity` ("not in the quotes") would misstate. |
| `unsupported_clause` | a part of the claim is covered by none of the cited quotes | a reviewer can trace the refusal to the uncovered clause, instead of a figure check that never fired. |

**VERIFIED (pipeline audit, step 5):** no backend or frontend code reads guard reasons or keeps a
closed list of them, so the codes are additive to the engine's report schema only. Darsh and
Chahit should still confirm nothing crashes on an unknown reason.

Not adopted: `unsupported_component` from the unmerged reference branch
`krish/round3-prior-work`. That branch is reference only and is never merged.

## 21. Messages to send (DRAFTS, NOT SENT)

**To Darsh and Chahit:**

> Round 3 contract for the Trust Scorecard. The proposal is in `docs/round3/contracts.md` on
> branch `krish/round3` (sections 15–20):
> 1. metric definitions: catch rate = flagged problematic ÷ all problematic; false-positive rate =
>    flagged SUPPORTED ÷ all SUPPORTED; ERROR counts as not flagged. These are the definitions the
>    engine and backend already compute. The engine's other "false-positive rate" (FP / (FP + TN),
>    CONTRADICTED only) gets the display label "False-CONTRADICTED rate"; no JSON key changes;
> 2. the headline is the held-out split only, always with numerator / denominator;
> 3. additive fields on `EvaluationOut`: `headline`, `run`, `stages`, `guard_regressions`,
>    `limitations`, and `coverage: "full_pipeline"`; no `contract` key;
> 4. one data path: I recommend the CLI's `summary.json` as the source of truth.
>
> Please reply "OK" or list changes by <time>. I won't change field names after your OK without
> telling you first.

**To Darsh only:**

> For routing: the proposed mapping from engine `verdict` / `review_reasons` to risk tiers is in
> section 19. Two new guard reason codes will appear in engine reports, `property_mismatch` and
> `unsupported_clause` (section 20); please confirm nothing in the backend breaks on an unknown
> reason. Also: the backend already applies the engine's decision policy (section 13), so the
> `limitations.py` note saying it doesn't is out of date. I'll correct it.

## 22. Acknowledgement log (STOP C)

No payload field changes and no step 08 work until **both** have replied in writing.

| Date | Name | Reply (verbatim) |
|---|---|---|
| | Darsh | *(none yet; message not sent)* |
| | Chahit | *(none yet; message not sent)* |
