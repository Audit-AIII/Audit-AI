# Trust Scorecard: two contracts that don't match (decision needed)

**From:** Darsh (backend) · **To:** Chahit (frontend), Krish (engine) · 2026-10-24

## The problem

The Scorecard page and the backend disagree on what `GET /api/evaluations/latest` returns.

- **The page** (`audit-ai-final/frontend/app/app/scorecard/Scorecard.tsx`,
  `lib/additions/analytics.ts` `parseEvaluation`) accepts **only** `contract: "evaluation-summary-v1"`
  (state `none` / `incomplete` / `available`), the engine's file-based summary
  (`inkloom_verify/evaluation/summary.py`). Anything else is treated as an error.
- **The backend** (`services/api/src/inkloom_api/routers/evaluations.py`) returns its own flat
  shape from `POST /api/evaluations` runs stored per account in the database, with **no
  `contract` key**.

Today this never shows, because no run has been stored (the page gets 404, which it shows as
"no evaluation yet"). **After the first successful run the page would show an error instead of
the numbers.**

## Field by field

| Backend (`GET /api/evaluations/latest`) | Engine `evaluation-summary-v1` | Same thing? |
|---|---|---|
| — | `contract`, `state` | missing in backend |
| `id` | `report_id` | roughly |
| `run_at` | `generated_at` | yes |
| `status` (`completed` / `partial`) | `state` (`available` / `incomplete`) | roughly |
| `sample_size` | `counts`, `dataset` | roughly |
| `catch_rate` (flagged = CONTRADICTED **or** NOT_ENOUGH_EVIDENCE, over claims that should be flagged) | `metrics[]` has `contradicted_recall` (CONTRADICTED only) | **no, different definition** |
| `false_positive_rate` (SUPPORTED claims flagged at all) | `metrics[].false_positive_rate` (non-CONTRADICTED claims flagged CONTRADICTED) | **no, same name, different definition** |
| `per_check` (catch / false-positive per labelled category) | — (`confusion`, `cases`) | no equivalent |
| `by_split` (dev / held-out, numerators and denominators) | — (per-split figures are in run_eval's report, not the summary) | no equivalent |
| `coverage` (`verifier_only`) | `source`, `decision_policy`, `retrieval` (full pipeline) | different scope |
| `provider_mode` (live / scripted) | `source.kind` (live model / oracle / replay …) | roughly |
| `engine_prompt_version`, `dataset_version` | `prompt_versions`, `dataset` | roughly |
| `limits_note` (one sentence) | `limitations[]` (structured) | roughly |
| `latency_ms_p50`, `provider_failure_rate` | — | backend only |
| — | 8 `metrics`, `gates`, `cases`, `confusion`, `review`, `corrections`, `stale` | engine only |

What each one measures:
- **Backend:** the verifier only (retrieval + verifier + citation guard per labelled claim), run
  from the app per account, stored in the database, with a "Run evaluation" endpoint.
- **Engine summary:** the full pipeline, produced by `eval/run_eval.py` on the command line or in
  CI and written to `eval/reports/*.summary.json`; no per-account run.

## Options

**A. The frontend adopts the backend shape** (recommended)
- Chahit: parse the flat shape in `analytics.ts`; show catch rate, false-positive rate (with the
  backend's definitions), `per_check`, and `by_split` (**held-out is the figure to quote**);
  say "verifier only" from `coverage`; add the "Run evaluation" button (`POST /api/evaluations`;
  409 and 429 messages are user-readable).
- Krish: nothing. This matches what you told us: "my report stays a CLI/CI artifact from
  run_eval.py, not an endpoint".
- Backend: nothing new; maybe add `contract: "backend-evaluation-v1"` so the page can tell the
  shapes apart.

**B. The backend serves the engine's `evaluation-summary-v1`**
- Backend: `GET /api/evaluations/latest` returns `inkloom_verify.evaluation.summary.latest_summary(reports_dir)`
  (`EVALUATION_REPORTS_DIR` already exists in config, unused).
- Costs: the numbers are global, not per account; the deployed server needs `run_eval.py`
  output files on its disk; `POST /api/evaluations` no longer fits the page (its result isn't a
  summary) and would have to be removed or hidden; no metric may be computed outside run_eval.
- Chahit: nothing (the page already parses it).

**Recommendation: A.** It works with the runs the app can actually do, keeps results per account,
and keeps the engine's report where Krish wants it. Whichever we pick, the two
`false_positive_rate`s must never be shown side by side under the same label.

Decision: _pending (Darsh / team)_.
