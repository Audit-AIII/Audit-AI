# Release report: prompt set v2 (candidate, not activated)

**Status:** candidate. **Recommendation: do not ship yet (deferred, not rejected).** v2 is
frozen and can be evaluated; v1 stays active. Nothing that decides between them has been
measured, because there's no live baseline and no approved model configuration.

Prepared 2026-10-23 (PROMPTS.md Phase 7). Every number below was measured by a command named
next to it. Anything unmeasured is listed as unmeasured.

## 1. Versions

| Stage | Active (old) | Candidate (new) | Notes |
|---|---|---|---|
| Extraction | `extract-claims-v1` (sha256 `d7f14fc3…`) | `extract-claims-v2` (`aa40979d…`) | +326 characters |
| Verification | `verify-claim-v1` (`5d850686…`) | `verify-claim-v2` (`b97e8bdb…`) | +518 characters |
| Correction | `correct-claim-v1` (`82602e69…`) | `correct-claim-v2` (`dd831a11…`) | +502 characters |

- **Both sets are in `prompts.lock.json`** and can't be edited in place (the loader refuses).
- **What v2 changes:** security wording only (PROMPTS.md "Prompt security"). It names the data
  block, calls the claim untrusted, says data can't change the rules, and says never to repeat the
  instructions. One rule was reworded: the verifier's "Decide using only the passages" became
  "Decide using only the facts the passages state".
- **Activation:** the components' defaults are v1. Phase 6 had switched them to v2; Phase 7
  switched them back, because activation needs an approved release. A test enforces that v1 stays
  the default (`test_v2_is_a_released_candidate_and_v1_stays_active`).
- **Recording versions:** every report records the versions sent: internal
  `provenance.prompt_versions`, public `metadata.prompt_versions`, and in evaluation reports
  `run.prompt_versions` and `verdicts.prompt_versions_sent`.

**What is not part of this choice.** The Phase 6 code checks are active whichever prompt is used:
- `instruction_text` in the citation guard;
- withholding an echoed prompt;
- repair messages that never echo the model's keys.

They are tested under both versions.

## 2. Datasets (locked in `eval/datasets.lock.json`)

| Set | Records | Labels | Human-reviewed |
|---|---|---|---|
| `eval/dataset.jsonl` (verdicts) | 55 | 20 SUPPORTED · 17 CONTRADICTED · 18 NOT_ENOUGH_EVIDENCE; 5 tagged `prompt_injection` | **0/55** |
| `eval/data/extraction_v1.jsonl` | 24 paragraphs, 33 claims | — | **0/24** |
| `eval/data/corrections_v1.jsonl` | 19 cases, 46 labelled edits | — | **untracked** (no `reviewed_by` field) |
| `eval/data/retrieval_v1.jsonl` | 34 | — | deterministic use only |

**Every label was written by Claude Code and checked mechanically. None has been reviewed by a
person.** Treat them as unreviewed until a team member fills in `reviewed_by`.

**The sets are small.** One CONTRADICTED record is 5.9 points of CONTRADICTED recall, and one
injection record is 20 points of the `prompt_injection` slice. Differences of one or two records
between v1 and v2 are within noise.

## 3. Model configuration

**None approved. No live run has been made with either prompt set.**

- **What a live run reads:** `OPENROUTER_API_KEY` and `INKLOOM_LLM_MODELS` (comma-separated, tried
  in order) from the environment.
- **Defaults:** temperature 0, seed 0, `json_schema` structured output, `data_collection=deny`, a
  30 s timeout, 2 retries.
- **This service has no `.env`.** The only key on this machine is in Member 3's
  `services/api/.env`. It's configured for `nvidia/nemotron-3.5-lightning:free`, which rejected
  requests in the site check. Whether to use that key, and which model, is your decision.
- **Recording:** every live report records the configuration (models, temperature, seed,
  structured output, data collection, timeout, retries; never the key) under
  `run.model_configuration`, and the model ids that actually answered under `verdicts.model_ids`.

## 4. What was measured (no live model)

| Measurement | v1 | v2 | Source |
|---|---|---|---|
| Deterministic gates (retrieval, enforcement, correction checker, extraction oracle and adversaries, faults) | 19 PASS | identical | `run_eval.py --check-baseline`. These sections don't send prompts, so they can't differ. |
| Prompt-injection regression tests, mocked obedient model | pass | pass | `tests/test_prompt_security.py` (the guard cases run under both versions) |
| Calls per run, measured offline | 24 extraction · 53 verification · 19 correction = **96** | **96** | `run_eval.py --verdicts openrouter --dry-run --prompts v1/v2` |
| Input characters per run (system + user) | 219,906 | 264,818 (**+20%**) | same dry run |

## 5. Not measured (needs a live run)

| Requested | Metric that will measure it | Report path |
|---|---|---|
| Claim extraction correctness | claim recall, precision, exact spans, not atomic, opinions extracted, unsafe rewordings | `extraction.live` |
| CONTRADICTED precision and recall | per-class precision and recall | `verdicts.per_class.CONTRADICTED` |
| Citation validity | citation validity, grounding | `verdicts.citation_validity`, `.grounding` |
| NOT_ENOUGH_EVIDENCE behaviour | NOT_ENOUGH_EVIDENCE precision and recall, abstention rate, false-SUPPORTED rate | `verdicts.*` |
| Correction safety | the live corrector: proposals, unsafe or false accepts, matches reference | `corrections.live` |
| Output-schema validity | repair calls and `MALFORMED_MODEL_OUTPUT` per stage; ERROR verdicts | `calls.*`, `verdicts.error_rate` |
| Prompt-injection regressions | accuracy on the 5 `prompt_injection` records | `verdicts.by_category.prompt_injection` |

## 6. Baseline: none is trustworthy yet

`eval/baseline.json` was measured with the `abstain` floor. It has no model-quality numbers, and
its model-run gates are `null` (reported as NOT ENFORCED). Three steps would establish one:

1. **Review the labels.** A team member checks the 55 verdict records, the 24 extraction
   paragraphs and the 19 correction cases, fills in `reviewed_by`, and updates the lock in the
   same reviewed commit.
2. **Approve one model configuration** (section 3) and the cost (section 7).
3. **Run each set three times with that configuration, interleaved, on the same day:**
   `run_eval.py --verdicts openrouter --prompts v1 --out reports/v1-run1`, then v2, and so on.
   Temperature 0 isn't fully deterministic at providers, so the run-to-run spread is the noise
   floor any difference must exceed. Keep the `predictions.jsonl` files, so results can be
   replayed with `--predictions`.

**Proposed release criteria** (for you to agree before any run):
- **Hard requirements:** all 19 deterministic gates pass; citation validity = 1.0; live
  correction false accepts = 0; no `prompt_injection` record answered SUPPORTED where the label
  isn't SUPPORTED.
- **Must not drop below v1** by more than the spread across v1's three runs: CONTRADICTED
  precision and recall, NOT_ENOUGH_EVIDENCE recall, false-SUPPORTED rate, extraction recall,
  precision and exact spans.
- **Must not exceed v1** by more than the spread: error rate, repair calls per stage.
- **Ship v2 only if every criterion holds.** Then record v2's median as the new model-run gates in
  `eval/baseline.json`.

## 7. Cost estimate

Measured call counts and input sizes (section 4). Tokens are estimated as characters ÷ 4, a rough
rule for English. Real counts depend on the model's tokenizer.

| Per run | v1 | v2 |
|---|---|---|
| First-attempt calls | 96 | 96 |
| Extra calls, expected | re-checks after proposed corrections (≤ 19), repairs | same |
| Input tokens (estimated) | ~55,000 | ~66,000 |
| Output tokens, hard cap (the `max_output_tokens` sum over first attempts: 24×4,000 + 53×1,500 + 19×1,000) | ≤ 194,500 | ≤ 194,500 |
| Worst case per stage (all repairs and retries, PROMPTS.md Phase 5) | 6× the calls of that stage | same |

**Cost per run ≈ input tokens × the model's input price + output tokens × its output price.**
Real replies are usually far below the caps; the first live run will measure them (`calls`). At
$1 per million input tokens, the input of one v2 run is about $0.07. Scale by the chosen model's
actual OpenRouter price; I haven't assumed a price. The proposed 3 + 3 runs need about 363,000
input tokens plus output. Free models cost nothing but are rate-limited and may reject requests,
as the configured one did.

## 8. Known limitations

- Labels are unreviewed, and the sets are small (section 2).
- There's no live baseline, so no model-quality difference between v1 and v2 is known.
- v2 is about 20% longer, which adds input cost and possibly latency (latency unmeasured).
- Prompt wording can't guarantee injection resistance; the code checks are what's enforced
  (PROMPTS.md "Prompt security", Remaining limitations).
- Member 3's pipeline uses its own adapters and doesn't call the corrector, so the live site
  wouldn't exercise `correct-claim-*` at all (INTEGRATION.md).

## Recommendation

**Do not ship v2 yet: defer.** There's no evidence against v2. The deterministic checks and
security tests pass under both versions. But the release rule is "ship only when agreed criteria
are met and no regression is found", and neither is possible without a reviewed dataset and a
live comparison. Next decisions for you:
1. Approve a model configuration and budget.
2. Agree or edit the release criteria above.
3. Optionally, review the labels first.

Activating v2 means changing `PROMPT_VERSION` in `src/inkloom_verify/prompts/{extraction,
verification,correction}.py`. That needs your approval.
