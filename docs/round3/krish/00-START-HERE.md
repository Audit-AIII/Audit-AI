# 00 — START HERE: Krish's Round 3 runbook

**Mission (from your plan):** own end-to-end verification reliability and produce *defensible held-out* results. Measured accuracy, not confident-sounding output.

These files turn your 2-page plan into steps you can run one at a time in Claude Code. They were written after reading the team repo (`Audit-AIII/audit-ai`, commit `1e416e5`), so file names, line numbers and numbers below are real, not guessed. Anything I could not verify is marked **[VERIFY]**.

---

## How to use

1. Copy this folder into the repo as `docs/round3/krish/`.
2. Open Claude Code at the **repo root**. For each step, paste:

   > Read `docs/round3/krish/00-START-HERE.md` (sections *Rules* and *Ground truth*), then execute `docs/round3/krish/<file>.md` exactly. Stop at every **STOP** gate and report what you found before continuing.

3. Do the steps in order. Do not skip a STOP gate.

| # | File | Plan section | Output | Needs | Effort* |
|---|---|---|---|---|---|
| 01 | `01-inspect-and-map-failure-paths.md` | §1 audit, §6 "inspect first" | `pipeline-audit.md`, both failures reproduced | — | S |
| 02 | `02-agree-contracts-and-metric-definitions.md` | §4, §6 "agree schemas" | `docs/round3/contracts.md` + written OK from Darsh and Chahit | 01 | S–M |
| 03 | `03-fix-guard-numeric-property-binding.md` | §2 (first bullet) | failing tests → fix → REG entry | 01 | M |
| 04 | `04-fix-guard-compound-claims.md` | §2 (second bullet) | failing tests → fix → REG entry | 03 | M |
| 05 | `05-evidence-grounded-corrections.md` | §3 | gap tests + fixes, corrections eval | 03, 04 | M |
| 06 | `06-expand-benchmark-and-freeze-heldout.md` | §1 (bullets 3–4) | ≥120 records, frozen held-out, reviewed labels | 03–05 | L |
| 07 | `07-run-full-pipeline-evaluation.md` | §1 (bullet 2), §4 | final held-out numbers, 3 runs, cassettes | 06 | M |
| 08 | `08-wire-trust-scorecard.md` | §4 (last bullet), §6 done-when | Scorecard shows the real run | 02, 07 | M |
| 09 | `09-finish-and-document.md` | §5 deliverables | all deliverables, docs, honest limitations | 08 | M |
| 10 | `10-optional-governance-and-tone-contribution.md` | "Contribute to all three outcomes" | handoffs to Darsh / tone owner | 02 | S |

\*My rough estimates (S ≈ a couple of hours, M ≈ half a day, L ≈ a day or more), not measurements. Your deadline was not given, so I did not map these to dates.

---

## Rules (from your plan, plus the ones this repo already enforces)

From the plan:
- Work in the existing codebase. **Do not rewrite working modules** without an agreed reason.
- Agree API/data contracts before parallel implementation; tell teammates before changing them.
- Small commits. Run the relevant tests. Integrate often.
- **No hardcoded metrics or findings in the final demo.** Real backend/evaluation data only.
- **Held-out records stay separate** from anything used to tune prompts, rules or retrieval.
- Tests first for both guard failures: **positive and negative regression tests before changing production behaviour.**

Already enforced by the repo (do not fight these):
- `eval/datasets.lock.json` hashes every evaluation input. Changing a label needs a matching lock change **in the same reviewed commit**.
- `eval/baseline.json` gates are **only ever tightened, never loosened**. `null` means "not measured"; set a number only from a real run.
- Never edit an existing held-out record to make a score better. Add a new record instead (EVAL.md "Editing the dataset").
- `data_collection: deny` stays on for live model calls. Do not relax it to get a model working.
- Never commit API keys. The engine reads **process environment only**, not `.env` files.

Added by me:
- **No dataset-specific strings in production code.** After every guard change run `grep -rn "Lumen" services/verification/src` and expect no new hits.
- **Every held-out look is logged** in `docs/round3/results/RUN_LEDGER.md` (step 07). Honesty about how many times held-out was viewed is part of "defensible".

---

## Ground truth (verified in the repo, 2026-10-27)

| Fact | Where |
|---|---|
| Pipeline order: extract → BM25 retrieve → verify + citation guard → correct (CONTRADICTED only, with re-check) → safer wording (NOT_ENOUGH_EVIDENCE only) → decision policy. Safer wording is part of the pipeline but **off by default** (`PipelineConfig.suggest_safer_wording = False`) | `services/verification/src/inkloom_verify/pipeline.py` `_run` (lines ~136–210), `PipelineConfig` (L84) |
| The default extraction prompt is **`extract-claims-v1`**. `extract-claims-v2` is used only when `run_eval.py --prompts v2` pins it | `services/verification/src/inkloom_verify/prompts/extraction.py` L10; `eval/run_eval.py` `PROMPT_SETS` |
| Full-pipeline evaluator already exists (`--pipeline full` is the default) | `services/verification/eval/run_eval.py`, `evaluation/pipeline_predictor.py` |
| Dataset: **80 records** (dev 55, held-out 25). Held-out = 10 CONTRADICTED, 8 NOT_ENOUGH_EVIDENCE, **7 SUPPORTED** | `eval/dataset.jsonl` |
| All labels are AI-written and synthetic (fictional "Lumen Goods"). **Human-reviewed: 0/80** | `EVAL.md` "Dataset v2" |
| Held-out has only 7 SUPPORTED records, so **one record moves the false-positive rate by 14.3 points** | computed from the above |
| Dataset validator **caps size at 50–100 records** and forces class shares (30/35/25/10 ±5) | `src/inkloom_verify/evaluation/dataset.py` lines 41–48 |
| Several tests hard-code 80 records | `tests/test_dataset_validation.py:289`, `test_run_eval.py`, `test_required_metrics.py:386`, `test_run_eval_pipeline.py:129,285,443` |
| **Guard failure A (open):** `v1-036` "cold for up to 12 hours" accepted on a quote saying cold = 24 h, hot = 12 h. Guard checks a figure is *present*, not what it attaches to | `EVAL.md` lines ~905–915; code: `citation_guard.py` `quantities()` L268, `support_problems()` L318 |
| **Guard failure B (open):** `v1-045` "USB-C and a wireless charging pad" accepted on a quote covering only USB-C | same; compound handling today is only a *review flag* (`decision_policy.py` L58–102), never a verdict change |
| Both failing records are **dev**, so fixing them does not contaminate held-out | `eval/dataset.jsonl` |
| The same bag-of-figures weakness exists in correction checks (`mispaired` in `correction_issues`) | `correction.py` L126–139 |
| **No complete live-model, full-pipeline run exists.** EVAL.md documents a verifier-only run with 30/80 answered; `limitations.py` documents a *different* live run (Gemini, 87.5% recall). **The two accounts disagree — reconcile before quoting any number** | `EVAL.md` L874–921, `evaluation/limitations.py` "Live model quality" |
| Backend Scorecard runs **verifier-only** coverage; `"full_pipeline"` is reserved but unused | `services/api/src/inkloom_api/evaluation_runner.py` L58, `services/api/API.md` ~L526 |
| Two Scorecard data paths exist (engine `summary.json` vs backend stored run); the frontend tells them apart by shape | `EVAL.md` L540–561, `audit-ai-final/frontend/lib/additions/evaluationRun.ts` `looksLikeRunEvaluation` |
| Two different things are called "false-positive rate" (denominator = SUPPORTED only vs SUPPORTED + NOT_ENOUGH_EVIDENCE) | `EVAL.md` L443–447 vs L829–840 |
| Backend routes review on `verdict != SUPPORTED` only, so the engine's decision policy does not apply in the app | `limitations.py` "Backend review routing" (marked *suspected*) |
| Team decided single-user accounts on 24 Oct; Round 3 commits to multi-user governance. Darsh's problem, but it affects the contract | `DECISIONS.md` |
| "Compliant model" in this repo means a model whose endpoint passes `data_collection: deny`. Options verified answering on 2026-10-24: `meta-llama/llama-3.3-70b-instruct`, `google/gemini-2.5-flash-lite`, `mistralai/mistral-small-3.2-24b-instruct`, `openai/gpt-oss-120b`; the OpenRouter account then had **$0 credit** | `DEPLOYMENT_READINESS.md` |

---

## Decisions I made for you — confirm or change

1. **[CONFIRM] Benchmark size: 120** (40 new records), with a **held-out of ~50** and ≥15 SUPPORTED in it. At 25 held-out records the numbers are too coarse to defend. Needs the validator cap raised (step 06).
2. **[CONFIRM] "Compliant model" = privacy-compliant endpoint (`data_collection: deny`)**, as the repo defines it. If the hackathon rules also restrict *which* models are allowed, tell me and step 07 changes.
3. **[CONFIRM] Headline numbers = held-out only**, with counts. Pooled dev+held-out numbers are never the headline (dev was used for tuning).
4. **[CONFIRM] Catch rate / false-positive rate definitions** follow your plan and match the repo's existing "Scorecard candidates" (step 02 writes them down). "Problematic" = labelled CONTRADICTED or NOT_ENOUGH_EVIDENCE.
5. **Final model is run three times**, and all three are reported (your own EVAL.md already says to set gates from the lowest of three).

---

## What I measured while writing this (so you can trust the approach)

I prototyped both guard ideas outside the repo against the real dataset (not committed, not production code):

- Both known failures are caught: `v1-036` (the claim's own words "cold / drinks / keeps" are tied to a *different* figure in the quote) and `v1-045` (the clause "include a wireless charging pad" shares no content word with the quote).
- A **naive** version was too strict: it wrongly downgraded 6 of 35 correct SUPPORTED claims (binding) and 23 of 35 (clause coverage) because of ordinary paraphrase (`holds` vs `Capacity:`, `released` vs `launched`). Steps 03 and 04 therefore specify the **narrower rules** that gave **0 of 35** false downgrades on dev + `retrieval_v1`.
- **Disclosure:** my prototype also printed the 15 SUPPORTED held-out records (0 downgraded). I changed the rules based on *dev* failures, but those 15 were seen once. Step 06 handles this by adding **fresh** held-out records that nobody has seen, and step 07 reports them separately.

---

## Setup (PowerShell, from the repo root)

```powershell
cd services\verification
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]" -c constraints.txt
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python eval\run_eval.py --check-baseline
.\.venv\Scripts\python eval\run_eval.py --verdicts oracle --check-baseline
```

All three must pass before you change anything. On commit `1e416e5` in my sandbox: `pytest` gave **1953 passed, 1 skipped, 3 xfailed**, and both `run_eval.py` checks exited 0. Your local numbers should match; if not, stop and find out why (step 01).
Live calls need these in the **same shell** (never commit them):

```powershell
$env:OPENROUTER_API_KEY = "<your key>"
$env:INKLOOM_LLM_MODELS = "<model id>"
```

---

## Definition of done (from your plan)

- [ ] Full pipeline evaluated (extraction → retrieval → verification → corrections)
- [ ] Both guards have passing positive **and** negative regression tests
- [ ] Metrics are reproducible by one command
- [ ] Frontend renders real Scorecard data (no hardcoded numbers)
- [ ] Held-out catch rate and false-positive rate published **with counts, denominators, sample size, model/configuration, date and limitations**

## Two things that differ from the team PDF I made earlier

- **Tone engine:** your plan does *not* assign it to you ("contribute" only). Step 10 covers your contribution. If the team assigns you the tone engine, say so and I will add a step.
- **Benchmark target:** your plan says "beyond 80"; I chose 120 and explain why in step 06.
