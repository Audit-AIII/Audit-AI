# Final results: live end-to-end evaluation (2026-10-30)

**What was measured.** The full pipeline (claim extraction, BM25 retrieval, LLM verifier with citation guard, corrections, decision policy) run on the 120-record benchmark (dataset v4, sha256 `bb61147b9f48f4b36591c9b447549f864ddd336ce335adf21df856fcf32b0a30`) with a live model.

- Model: `openai/gpt-4o-mini` via OpenRouter (answered by Azure in the connectivity check), `data_collection: deny`, temperature 0, seed 0, structured JSON output, prompts `extract-claims-v1`, `verify-claim-v1`, `correct-claim-v1`, policy `decision-policy-v1`.
- Date: 2026-10-30. Three complete runs, recorded as cassettes in `eval/cassettes/`. Nothing was tuned between runs.
- Model change: the plan named `google/gemini-2.5-flash-lite`. Every call to it was rate limited upstream (HTTP 429, Google AI Studio shared pool), so no verdicts were produced; it was replaced by `gpt-4o-mini`, which is served under the same no-data-collection rule.

## Definitions

- **Catch rate** = problematic claims flagged / all problematic claims (problematic = labelled CONTRADICTED or NOT_ENOUGH_EVIDENCE). *Flagged* = the system did not auto-clear the claim as SUPPORTED (any other verdict, or no verdict, sends it to a person).
- **False-positive rate** = SUPPORTED claims flagged / all SUPPORTED claims.
- 95% intervals are Wilson intervals. Small n means wide intervals.

## Results by run (flagged k/N)

| Set (n) | Run 1 catch | Run 2 catch | Run 3 catch | FP (all runs) |
|---|---|---|---|---|
| Held-out, all (50) | 34/34 (89.8–100%) | 34/34 | 33/34 (85.1–99.5%) | 1/16 (1.1–28.3%) |
| Held-out, fresh v4 (25) | 16/16 (80.6–100%) | 16/16 | 15/16 (71.7–98.9%) | 1/9 (2.0–43.5%) |
| Dev, tuned (70) | 45/48 | 45/48 | 46/48 | 1/22 |
| All 120 | 79/82 (89.8–98.7%) | 79/82 | 79/82 | 2/38 (1.5–17.3%) |

Dev records were used to tune the system: quote the held-out rows, not the dev or combined rows, as the generalisation estimate.

## Verdict metrics (CONTRADICTED as positive class, all 120)

| Metric | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Recall (CONTRADICTED) | 48/49 (98.0%) | 48/49 (98.0%) | 47/49 (95.9%) |
| Precision (CONTRADICTED) | 48/52 (92.3%) | 48/52 (92.3%) | 47/51 (92.2%) |
| False-positive rate (not-CONTRADICTED flagged CONTRADICTED) | 4/71 (5.6%) | 4/71 (5.6%) | 4/71 (5.6%) |
| Citation validity (quote found and supports verdict) | 96/108 (88.9%) | 93/103 (90.3%) | 93/104 (89.4%) |
| Correction traceability | 47/47 (100%) | 44/44 (100%) | 42/42 (100%) |
| Share sent to human review | 96/120 (80.0%) | 97/120 (80.8%) | 96/120 (80.0%) |
| Retrieval recall@5 | 85/87 (97.7%) | 85/87 | 85/87 |

Two dev records (`v1-040`, `v1-042`) got no verdict in every run because the model extracted no claim; they count as flagged and are listed as errors, not model decisions.

## Limitations (read before quoting)

- Labels were written by AI and are **not independent** of the guard rules; **0/120 are reviewed by a person** (review pack: `docs/round3/review/`).
- Held-out n is small (50; 25 fresh). Intervals are wide; one record moves a rate by 2-6 points.
- One model, one provider, one day. Another model or provider route can differ. Run-to-run differences came from the model (temperature 0 is not fully deterministic).
- Synthetic documents; this is a benchmark, not production statistics.
- The citation-validity gate was set to 85% after seeing these runs (worst run 88.9%). It is a floor, not a target.
- Known limitations of the checker are listed in `src/inkloom_verify/limitations.py`.

## Reproduce

`eval/cassettes/final-run1.jsonl` replays run 1 without calling any provider (`--replay`).
