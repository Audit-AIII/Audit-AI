# 01 — Inspect the pipeline and map the exact failure paths

**Plan §1 (audit the pipeline) + §6 ("inspect current verification code and identify exact failure paths before rewriting anything").**
**This step changes no production code.** Output: `docs/round3/krish/pipeline-audit.md`.

## Paste into Claude Code

> Read `docs/round3/krish/00-START-HERE.md` (Rules, Ground truth), then execute `docs/round3/krish/01-inspect-and-map-failure-paths.md`. Read-only except for the audit document and throwaway scripts under `%TEMP%`. Stop at every STOP gate.

## Step 1 — Baseline must be green

From `services\verification`:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python eval\run_eval.py --check-baseline
.\.venv\Scripts\python eval\run_eval.py --verdicts oracle --check-baseline
git rev-parse HEAD
```

Record the commit, pass counts and exit codes at the top of `pipeline-audit.md`.

**STOP A:** if anything is red, do not continue. Report the failing test names. (Reference: commit `1e416e5` gave 1953 passed / 1 skipped / 3 xfailed.)

## Step 2 — Stage map (verify every row, fix wrong ones)

Create a table in `pipeline-audit.md`. I pre-filled it from reading the code; **confirm each row by opening the file** and correct anything stale.

| Stage | Module / entry point | Deterministic guard on its output | Tests to read |
|---|---|---|---|
| Extraction | `extraction.py` `ClaimExtractor.extract`; prompt `prompts/extract-claims-v2.txt` | `rewrite_problems`, `locate` (claim must be traceable to its source span) | `test_extraction.py`, `test_extractor_prompt.py`, `test_extraction_eval.py` |
| Retrieval | `retrieval.py` `BM25Retriever.for_request`; `chunking.py` | recall gates in `eval/baseline.json` | `test_retrieval.py`, `test_retrieval_eval.py` |
| Verification | `verification.py` `verify_claim`, `ClaimVerifier` | `citation_guard.py` `CitationGuard.check` + `support_problems` + `conflicting_passage` | `test_verification.py`, `test_citation_guard.py`, `test_verifier_prompt.py` |
| Correction | `correction.py` `ClaimCorrector.correct`; `intent_lock.py` | `correction_issues` (unsupported additions, dropped unit/qualifier/attribution, minimality) + re-verify as SUPPORTED | `test_correction*.py`, `test_intent_lock.py` |
| Decision policy | `decision_policy.py` `apply_policy` | adds review reasons only; never removes review | `test_decision_policy.py` |
| Report | `pipeline.py` `_report`, `schemas.py` | `scope.py` `check_report_scope` | `test_pipeline.py`, `test_report*.py` |
| Evaluation | `evaluation/runner.py`, `pipeline_predictor.py`, `required_metrics.py`, `summary.py`, `report.py` | label lock + baseline gates | `test_run_eval*.py`, `test_required_metrics.py` |

Also answer, from the code, in the audit file:
- Which stages call the model, and which are deterministic?
- Where does a provider failure become `ERROR`, and does it ever become `SUPPORTED`? (It must not. Check `test_provider_failure_never_approved.py` in `services/api` and `test_partial_failure.py`.)
- What does the **verifier-only** path skip compared with `--pipeline full`? (Extraction, corrections, decision policy. The backend Scorecard uses verifier-only today.)

## Step 3 — Reproduce failure A (figure bound to the wrong property)

Write a throwaway script in `%TEMP%` (not in the repo). Use `support_problems` directly:

```python
from inkloom_verify.citation_guard import support_problems, quantities
claim = "The Lumen Bottle keeps drinks cold for up to 12 hours."
quote = "keeps drinks cold for up to 24 hours and hot for up to 12 hours"
print(quantities(claim), quantities(quote))
print(support_problems(claim, [quote]))
```

**Expected today:** `support_problems` returns `[]`, i.e. the quote is treated as supporting the claim.

Then open `citation_guard.py` L268–354 and write down in the audit **why**: `quantities()` returns a *set of (number, unit)* with no link to the words around each number, and `support_problems` only tests set membership (L329–337).

Also load the real record: `v1-036` in `eval\dataset.jsonl` (dev, CONTRADICTED, gold "keeps drinks cold for up to 24 hours").

**Second location of the same defect:** `correction.py` L126–139. A *replacement* figure passes the `mispaired` check if `(number, unit)` appears **anywhere** in the evidence quotes. Reproduce with `correction_issues(original, replacement, quotes)` using the same quote and a replacement that borrows the hot figure for the cold claim. Record the result.

## Step 4 — Reproduce failure B (compound claim half-supported)

```python
claim = "Lumen Pods charge over USB-C and include a wireless charging pad."
quote = "Charging: USB-C."   # use the real record's reference text for v1-045
print(support_problems(claim, [quote]))
```

**Expected today:** `[]` (no figures, no dates, no negation difference, so every existing support check passes).

Then trace what *does* look at compounds: `decision_policy.py` L58–102 (`looks_compound`, `compound_under_cited`). Write down: **it only adds a review reason; the verdict stays SUPPORTED.** The Scorecard counts verdicts, so it still counts as a wrong approval.

Check what extraction does for this sentence with a scripted provider (`providers/fake.py`, `evaluation/scripted.py`): does the full pipeline split it? What if the model returns it unsplit (simulate in a scripted test)? Record both answers. This is the key question for step 04: **the extraction prompt asks for splitting but nothing in code enforces it.**

## Step 5 — Find every file a new guard reason would touch

```powershell
cd ..\..
git grep -n "unsupported_quantity\|UNSUPPORTED_QUANTITY" -- . ":!node_modules"
```

Expected touchpoints (confirm): `schemas.py` `GuardRejectionReason` (~L1183), generated `services/verification/schemas/verification_report.schema.json` (~L576), `CONTRACTS.md` (~L262), `PROMPTS.md` (~L421). Also check the backend and frontend for a **mapping or label table** of guard reasons (I found none, **[VERIFY]**). List every hit; steps 03 and 04 add reason codes and must update all of them.

Schema regeneration command: `python -m inkloom_verify.json_schema` from `services\verification`. A test fails if committed schemas drift.

## Step 6 — List tests and gates that pin today's behaviour

Because steps 03 and 04 will change guard behaviour, list what could legitimately change:
- `eval/baseline.json` gate "valid-quote, always-SUPPORTED false-SUPPORTED ≤ 16/55" (from `EVAL.md`). A correct fix should **lower** this measured number. Gates may be tightened afterwards, never loosened.
- `tests/test_known_limitations.py` and `evaluation/limitations.py` (pinned limitations).
- `tests/test_verification_eval.py` (adversary numbers).

For each, write: "expected to change: yes/no, and in which direction."

## Step 7 — Write the audit and the "do not touch" list

`pipeline-audit.md` must end with:
1. **Failure paths** for A and B (file, function, line, why, reproduction command).
2. **Fix locations** you propose (guard in `citation_guard.py`; extraction atomicity check in `extraction.py`; correction reuse in `correction.py`).
3. **Do-not-touch list:** modules that work and have strong tests (retrieval, chunking, security, intent lock, report scope). Rewriting these needs a written reason.
4. **Open questions** for the team.

**STOP B:** show me (and Darsh/Chahit if the audit changes a contract) the audit before step 03.

## Done when

- [ ] Baseline green, commit recorded
- [ ] Both failures reproduced with a command, and the exact reason written down
- [ ] The same defect located in `correction_issues`
- [ ] Touchpoint list for new guard reasons
- [ ] `pipeline-audit.md` committed (docs only): `docs: round 3 pipeline audit`
