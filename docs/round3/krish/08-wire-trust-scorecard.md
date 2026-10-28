# 08 — Show the real run in the Trust Scorecard

**Plan §4 (last bullet: agree a stable Scorecard contract) and §6 done-when ("frontend renders real Scorecard data").**
Depends on 02 (contract + both teammates' OK) and 07 (a real run exists). Chahit owns the frontend and Darsh the backend; this step is the **joint** integration, so you coordinate and verify rather than write all of it.

## Paste into Claude Code

> Read `docs/round3/krish/00-START-HERE.md`, `docs/round3/contracts.md` and `docs/round3/krish/08-wire-trust-scorecard.md`. Do not change any field named in contracts.md without telling Darsh and Chahit. Show me the payload the page receives before touching UI code. Stop at every STOP gate.

## What exists today (verified in the clone)

- Backend: `services/api/src/inkloom_api/routers/evaluations.py` — `GET /api/evaluations/latest` (404 until a run exists) and `POST /api/evaluations` (runs **verifier-only**, stores it, 1 run / 10 min / user). `evaluation_runner.py` sets `coverage` to `"verifier_only"`. The shape `EvaluationOut` already has `catch_rate`, `false_positive_rate`, `per_check`, `sample_size`, `by_split` (ratios with numerator/denominator), `provider_mode`, `provider_failure_rate`, `coverage`, `limits_note`. Contract rule: **no `contract` key; additive fields only** (`services/api/API.md` ~L520–540).
- Frontend (note the folder: `audit-ai-final/frontend/`): `lib/additions/evaluationRun.ts` (type + `runEvaluationProblem` validator + `looksLikeRunEvaluation`), `lib/additions/analytics.ts` (switches between engine summary and stored run), `app/app/scorecard/Scorecard.tsx` and `RunReport.tsx`. The validator rejects the whole response if a listed field has the wrong type; extra fields are tolerated, so additive fields are safe.
- QA scripts: `audit-ai-final/frontend/qa/scorecard-run.mjs`, `scorecard-live.mjs`, `insights-scorecard-live.mjs`; fixture `qa/fixtures/evaluation-run.api-example.json`.

## Step 1 — Implement the data path chosen in step 02

### Option 1 (recommended): the CLI's `summary.json` is the source of truth
1. Decide with Darsh where the published run lives (a committed file such as `services/verification/eval/published/final-summary.json`, or a DB row loaded by a one-off command). It must be the **exact** `<timestamp>.summary.json` from step 07 run 1/2/3 (the worst run for headline claims — say which).
2. Backend maps summary → `EvaluationOut` additively: `coverage: "full_pipeline"`, `headline` (held-out), `run` (model, prompts, dataset sha256, commit, date), `limitations`, `guard_regressions` as in contracts.md. **No numbers are computed in the backend** — it copies the runner's. If a field is missing in the summary, the response says so; it does not default to 0.
3. `GET /api/evaluations/latest` serves it; the 404-until-run behaviour stays.

### Option 2: the backend runs the full pipeline itself
Swap the predictor to the engine's `PipelinePredictor`. Cost/time risk (full pipeline is slower than verifier-only, which already takes minutes; the demo host's request timeout is unknown **[VERIFY]**). Only choose this if Darsh confirms timeouts and credit. Even then, the page should default to the **published** run and offer re-run as secondary.

## Step 2 — Frontend: what the page must show (plan §4)

For the headline (held-out): catch rate and false-positive rate **as k/N with the percentage**, sample size, model/configuration, prompt version, dataset version/hash, run date, `provider_mode` (live vs scripted badge — the page already distinguishes), coverage (`full_pipeline`), the limitations list, and guard-regression status (two guards × passed/total). Dev/pooled numbers, if shown, are labelled "tuned on this data".

Rules for Chahit's UI:
- Nothing hardcoded. `git grep -n "catch_rate\|\b0\.\(8\|9\)\d" audit-ai-final/frontend/app audit-ai-final/frontend/components` must show no literal result numbers (the fixture is for tests only).
- Empty/404/partial states render honestly ("not available yet", "partial: n provider failures"). Never "undefined", never 0% for null.
- A scripted/oracle run must not look like a live one.

## Step 3 — Verify end to end (the check that matters)

1. Start the backend and frontend as in `README.md` (steps 1–2), load the Scorecard.
2. Open the network payload and the page side by side. Every number on screen must equal the `summary.json` value. Take a screenshot pair.
3. Run the existing QA scripts (`node qa/scorecard-run.mjs` etc. — read their header comments for prerequisites) and add one case for `coverage: "full_pipeline"`.
4. Break it on purpose: serve a summary with a null denominator; the page must show "n/a".

**STOP J:** Darsh and Chahit sign off in writing (date, name) in `contracts.md` after seeing the screenshot pair.

## Done when
- [ ] Page shows the real held-out numbers with counts, n, model/config, date, limitations
- [ ] No metric computed outside the runner; no hardcoded result numbers in the frontend
- [ ] Payload ≡ summary file; screenshot evidence saved in `docs/round3/results/`
- [ ] QA scripts pass; contract additions documented in `services/api/API.md` (additive only)
