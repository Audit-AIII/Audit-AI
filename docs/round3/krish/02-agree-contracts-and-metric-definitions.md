# 02 — Agree contracts and metric definitions

**Plan §4 (Metrics and Trust Scorecard contract) + §6 ("agree on finding/risk/metric schemas with Darsh and Chahit").**
**Rule from the plan:** agree contracts *before* parallel implementation, and notify teammates before changing them.
Output: `docs/round3/contracts.md` + a written OK from Darsh and Chahit. No production code yet.

## Paste into Claude Code

> Read `docs/round3/krish/00-START-HERE.md` (Rules, Ground truth), then execute `docs/round3/krish/02-agree-contracts-and-metric-definitions.md`. This step writes documents and message drafts only. Stop at every STOP gate.

## Why this step exists (what the repo shows today)

- Catch rate and false-positive rate are already computed in two places (`evaluation/runner.py` "scorecard candidates", `services/api/src/inkloom_api/evaluation_runner.py`), and EVAL.md says the definitions are **"not yet agreed"** with the Scorecard owner.
- A second metric is also called "false-positive rate" in `required_metrics.py` but uses a **different denominator** (SUPPORTED + NOT_ENOUGH_EVIDENCE). Two numbers with one name on one page is exactly what a judge will catch.
- The backend Scorecard reports `coverage: "verifier_only"`; the plan needs the **full pipeline**.
- Two payload shapes exist (engine `summary.json`, backend `EvaluationOut`). The frontend tells them apart by shape.

## Step 1 — Write the metric definitions (adopt these unless you object)

Put this in `docs/round3/contracts.md`, section "Metrics". It is your plan's wording mapped onto the repo's labels.

| Term | Definition |
|---|---|
| **Problematic claim** | a record labelled `CONTRADICTED` or `NOT_ENOUGH_EVIDENCE` |
| **Flagged** | the engine's final record verdict is `CONTRADICTED` or `NOT_ENOUGH_EVIDENCE` (what the product shows as a problem) |
| **Catch rate** | problematic claims that were flagged ÷ all problematic claims |
| **False-positive rate** | claims labelled `SUPPORTED` that were flagged ÷ all `SUPPORTED` claims |
| `ERROR` / provider failure | counts as **not flagged**: a miss on a problematic claim, never a false positive. Reported separately as `provider_failure_rate`. A run with any ERROR is marked `partial`. |
| Zero denominator | the value is `null` and shown as "n/a", never 0% or 100% |

Add two companion numbers so catch rate cannot hide behind the broad definition:
- **CONTRADICTED recall**: records labelled CONTRADICTED predicted CONTRADICTED ÷ records labelled CONTRADICTED (already computed in `required_metrics`).
- **Wrong approvals**: records predicted SUPPORTED whose label is not SUPPORTED, with counts (already in the confusion matrix).

Every published rate carries **numerator / denominator**, `n`, split, model/configuration, dataset hash, date and limitations (plan §4).

**Resolve the name collision.** Find where `required_metrics` prints "False-positive rate" (EVAL.md L443–447). Pick the smallest change that makes it impossible to confuse with the Scorecard number, for example relabel it "false-CONTRADICTED rate" in the Markdown/JSON display text. `git grep -n "false_positive_rate"` first and list every consumer (backend, frontend, schemas, tests). Do **not** rename a JSON key that the backend or frontend reads without telling Darsh and Chahit.

**[CONFIRM #4]** from `00-START-HERE.md`: show these definitions to Krish (you), then to the team.

## Step 2 — Decide the headline

Write: **"The headline is the held-out split only."** Reason (already in `EVAL.md` and `API.md`): dev records were used to tune the engine, so pooled numbers are optimistic. The existing payload already has `by_split.heldout`; the contract must make that the *named headline* rather than something the UI has to pick.

## Step 3 — Propose the Scorecard payload (additive only)

The backend contract states: **no `contract` key, ever; new fields are additive only** (`services/api/API.md` ~L520). Respect that. Propose these new fields on top of the existing `EvaluationOut` (field names are proposals; align with Darsh):

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
    "models": ["<model id>"], "prompt_versions": {"extract_claims": "…", "verify_claim": "…", "correct_claim": "…"},
    "retrieval": {"strategy": "…", "top_k": 5}, "decision_policy_version": "decision-policy-v1",
    "dataset": {"path": "eval/dataset.jsonl", "sha256": "…", "records": 0, "human_reviewed": 0},
    "git_commit": "…"
  },
  "stages": { "extraction": {}, "retrieval": {}, "verification": {}, "corrections": {} },
  "guard_regressions": { "numeric_binding": {"passed": 0, "total": 0}, "compound_claims": {"passed": 0, "total": 0} },
  "limitations": [ {"topic": "…", "status": "measured|suspected|unsupported|not_implemented", "finding": "…"} ],
  "provider_failure_rate": 0.0
}
```

**Everything above is a shape, not data.** The zeros and nulls are placeholders. A fixture with placeholder numbers must never be rendered as a result (the frontend already labels scripted vs live; keep that).

Existing sources to reuse instead of reinventing: `evaluation/summary.py` (`EvaluationSummary`, contract `evaluation-summary-v1`), `schemas/evaluation_summary.schema.json`, `evaluation/limitations.py`, and the fixture `audit-ai-final/frontend/qa/fixtures/evaluation-run.api-example.json`.

## Step 4 — Choose ONE data path (decision for Darsh + you)

| Option | How | Pros | Cons |
|---|---|---|---|
| **1. CLI is the source of truth (recommended)** | You run `eval\run_eval.py`; the engine writes `<timestamp>.summary.json`; the backend serves/ingests that file | reproducible by one command (plan §5); no cost or timeout in the demo; the exact artifact is the published artifact | needs an ingest/serve path for the file |
| 2. Backend runs the full pipeline itself | swap the predictor in `evaluation_runner.py` to the engine's `PipelinePredictor`, set `coverage: "full_pipeline"` | "live re-run" button works | the existing POST already takes ~1–4 min verifier-only; full pipeline is slower; rate-limited to 1 run / 10 min / user; costs money on every click; **[VERIFY]** whether the demo host's request timeout allows it |

Whichever is chosen, the rule from EVAL.md stands: **no metric is computed outside the runner.** The page displays the runner's numbers; it never recomputes them.

## Step 5 — Risk / finding fields the backend needs from the engine

Plan §6 asks you to agree finding/risk schemas with Darsh. Today the engine already emits per claim: `verdict`, `requires_human_review`, `review_reasons` (`contradicted`, `not_enough_evidence`, `error`, `weak_evidence`, `below_policy_strength`, `compound_under_cited`), `evidence_strength`. The backend routes on `verdict != SUPPORTED` only (`limitations.py` says *suspected*; **[VERIFY]** in `services/api/src/inkloom_api/approval_rules.py` and `review_runner.py`).

Write a proposal table for Darsh (he owns routing):

| Engine signal | Proposed routing input |
|---|---|
| verdict CONTRADICTED | high risk → reviewer queue |
| verdict NOT_ENOUGH_EVIDENCE or ERROR | medium → reviewer queue |
| SUPPORTED with any `review_reasons` | low → reviewer queue (policy says a person should look) |
| SUPPORTED, no `review_reasons` | clean → approver only |

Also add: the two new guard reason codes from steps 03 and 04 will arrive as `guard.rejected[].reason`; the backend must pass unknown reasons through without crashing (**[VERIFY]** the backend/frontend do not use a closed list).

Mention `DECISIONS.md` (single-user decision of 24 Oct) so nobody is surprised that routing is "deferred, not built" in the repo while Round 3 commits to it. That is Darsh's conversation, not yours.

## Step 6 — Send these messages (edit freely)

**To Darsh and Chahit:**
> Round 3 contract for the Trust Scorecard. Proposal in `docs/round3/contracts.md`: (1) metric definitions (catch rate = flagged problematic ÷ all problematic; FPR = flagged SUPPORTED ÷ all SUPPORTED; ERROR counts as not flagged); (2) the headline is the held-out split only, with numerator/denominator; (3) additive fields `headline`, `run`, `stages`, `guard_regressions`, `limitations`, `coverage: "full_pipeline"`; (4) one data path (I recommend the CLI's `summary.json` as source of truth). Please reply "OK" or list changes by <time>. I will not change field names after your OK without telling you first.

**To Darsh only:**
> For routing: proposed mapping from engine `verdict`/`review_reasons` to risk tiers is in section 5 of the doc. Two new guard reason codes will appear (property binding, unsupported clause); please make sure nothing breaks on an unknown reason.

## STOP gates

**STOP C:** do not start step 08, and do not change any payload field, until Darsh **and** Chahit have each replied in writing. Record their replies (date, name, wording) at the bottom of `contracts.md`.

## Done when

- [ ] `docs/round3/contracts.md` has: definitions, headline rule, payload shape, data-path decision, risk mapping, and the ack log
- [ ] The "false-positive rate" name collision is resolved or the plan to resolve it is written down
- [ ] Both teammates acknowledged in writing
- [ ] Committed: `docs: round 3 scorecard contract and metric definitions`
