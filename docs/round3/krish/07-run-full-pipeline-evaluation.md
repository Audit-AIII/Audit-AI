# 07 — Run the full-pipeline evaluation with a compliant model and publish held-out numbers

**Plan §1 (bullet 2) and §4.** Output: three recorded live runs, one headline table, a run ledger, reproducible by one command.

Prerequisites: steps 03, 04, 05 merged; step 06 finished (STOP H). **Do not start this step if the held-out freeze is not committed.**

## Paste into Claude Code

> Read `docs/round3/krish/00-START-HERE.md`, then execute `docs/round3/krish/07-run-full-pipeline-evaluation.md`. Always dry-run before a paid run, log every held-out look in the ledger, and stop at every STOP gate. Never print or commit an API key.

## What already exists (verified)

`eval/run_eval.py --verdicts openrouter` runs the **full pipeline** (`--pipeline full` is the default): `verify_request` once per record = extraction → retrieval → verification + guard → correction → decision policy. It writes `report.json`, `report.md`, `cases.jsonl` and `<timestamp>.summary.json` (contract `evaluation-summary-v1`), records model/config/prompt versions and per-stage call counts, and supports cassettes (`--record FILE` live, `--replay FILE` offline and deterministic). `--prompts v1|v2` pins prompt sets. `--dry-run` counts calls offline.

Reports go to `eval/reports/<UTC timestamp>/` and are **gitignored**. What you commit is: the cassettes you choose to keep, the summary you publish, and the ledger.

## Step 1 — The model (decision made by Krish, 2026-10-28)

Use **`google/gemini-2.5-flash-lite` through OpenRouter**: per Krish, the only model that has run cleanly under `data_collection: deny` in this project. (`DEPLOYMENT_READINESS.md` also lists llama-3.3-70b, mistral-small-3.2 and gpt-oss-120b as having answered on 2026-10-24; they stay fallbacks, not the plan.) Check the OpenRouter credit balance first: on 2026-10-24 it was $0.

Set both variables in the **same shell that runs the evaluation** (never in a file, never committed):

```powershell
$env:OPENROUTER_API_KEY = "<your key>"
$env:INKLOOM_LLM_MODELS = "google/gemini-2.5-flash-lite"
```

Do not pick or change the model by looking at held-out results. If the hackathon defines "compliant" differently, tell me and this step changes.

## Step 2 — Dry run (free)

```powershell
cd services\verification
$env:OPENROUTER_API_KEY = "<key>"      # same shell only, never committed
$env:INKLOOM_LLM_MODELS = "<model id>"
.\.venv\Scripts\python eval\run_eval.py --verdicts openrouter --dry-run
```

Record from the output: calls per stage × records → total calls, input size. Multiply by the model's price (read it from the provider's page, do not guess) to get the cost of one run; the final plan is **three runs**.

**STOP I:** show the call count and the cost estimate before spending anything.

## Step 3 — Smoke run on dev only

```powershell
.\.venv\Scripts\python eval\run_eval.py --verdicts openrouter --dataset eval\data\dev_only.jsonl --out %TEMP%\smoke
```

Check: no `provider_failure` explosion (rate limits, malformed JSON), report shows model/prompt versions, `cases.jsonl` has one row per record. Fix configuration, never the labels. A run where most records got no verdict exits 3; do not "fix" that by lowering a gate.

## Step 4 — The final runs (3 × full dataset)

Record each run to its own cassette so anyone can replay it offline:

```powershell
.\.venv\Scripts\python eval\run_eval.py --verdicts openrouter --record eval\cassettes\final-run1.jsonl
.\.venv\Scripts\python eval\run_eval.py --verdicts openrouter --record eval\cassettes\final-run2.jsonl
.\.venv\Scripts\python eval\run_eval.py --verdicts openrouter --record eval\cassettes\final-run3.jsonl
```

(Create `eval/cassettes/`. **[VERIFY]** it is not gitignored and that cassettes contain no secrets: they hold the synthetic prompts and model replies, never the key. Open one and grep for the key's first 6 characters before committing.)

After each run append a ledger line (`docs/round3/results/RUN_LEDGER.md`): UTC time, command, git commit, model, split(s) viewed, report folder, what you changed afterwards (should be **nothing**).

**Rule:** after the first look at fresh held-out, you may not change prompts, rules, retrieval or code and then re-report the same split as clean. If something is broken, write the failure in the ledger and in the limitations; if you fix it, start a new numbered series and report the old one too.

## Step 5 — Replay proves reproducibility

```powershell
.\.venv\Scripts\python eval\run_eval.py --replay eval\cassettes\final-run1.jsonl --out %TEMP%\replay1
```

The summary numbers must be **identical** to run 1. Add this as the "one reproducible command" in the README (plan §5) and as a CI test if the repo's CI can run it offline.

## Step 6 — Read the numbers (the table you publish)

Take every figure from `<timestamp>.summary.json`; type nothing by hand. Definitions come from step 02.

| Split | n | Problematic | Catch rate (flagged ÷ problematic) | SUPPORTED | False-positive rate (flagged ÷ SUPPORTED) | CONTRADICTED recall | Wrong approvals |
|---|---|---|---|---|---|---|---|
| Held-out fresh (25) | | | k/N | | k/N | | |
| Held-out all (50) | | | | | | | |
| Dev (70) *(tuned; do not headline)* | | | | | | | |

For each cell: numerator / denominator, never a bare percentage. Add: provider/model, prompt versions, retrieval config, decision policy version, dataset sha256, git commit, date, run number (1–3). **Report all three runs.** Gates and headline claims use the **worst** of three (EVAL.md already says to set gates from the lowest of three). If runs disagree a lot, that variance is itself a finding.

Add the interval: for k/N use a Wilson 95% interval and print it (e.g. catch 21/32 → 48%–81%). It stops anyone from reading 25 records as precision. Compute it in the eval code or a small documented script; do not do it by hand.

Also report the pieces the plan calls "full pipeline": extraction (claims extracted vs labelled, atomicity), retrieval recall@k, verification, corrections (step 05 table), provider failure rate, and how many records ended `NEEDS_HUMAN_REVIEW`.

## Step 7 — Reconcile the conflicting live-run accounts

`EVAL.md` L874–921 documents a verifier-only run (30/80 answered); `evaluation/limitations.py` ("Live model quality") documents a different run (Gemini, 87.5% recall). Decide which still stands, label the older as superseded by the new three-run series, and update **both** places in the same commit so the repo no longer disagrees with itself.

## Step 8 — Tighten gates, never loosen

`eval/baseline.json`: set model-run gates from the **lowest** of the three runs, and only the gates this run actually measured. A `null` stays `null` if you did not measure it.

## Done when

- [ ] Three live runs recorded; three cassettes; ledger lines; replay reproduces run 1 exactly
- [ ] Published table with counts, denominators, n, intervals, model/config/date/commit, limitations
- [ ] Held-out numbers separate from dev; fresh vs all-held-out both shown
- [ ] Conflicting live-run documentation reconciled
- [ ] Gates tightened from the worst run; nothing loosened
- [ ] No key in any file (`git grep -n "sk-or"` is empty)
