# Steps 6–7: engine ↔ backend integration, and the AI side of the review workflow

**From:** Krish (Member 2, engine) · **To:** Darsh (backend), Chahit (frontend) · 2026-10-24

This lists what the engine now provides, the gaps found when testing it end to end through the
backend, and the exact changes each owner needs to make. Nothing in `services/api` (other than one
new test file) or in the frontend was changed.

**How it was tested:** `services/api/tests/test_engine_integration.py`. It runs real routes, real
Postgres, the real engine, and the backend's own evidence check, with only the model scripted.

- **13 tests pass:** all three verdicts with provenance, traceable corrections, invalid, malformed
  and missing model output, a fabricated quote, missing evidence, provider failures, and partial
  failures.
- **3 strict expected failures (`xfail(strict=True)`) pin the backend gaps below.** When a gap is
  fixed, its test starts passing, pytest reports it as an unexpected pass and fails it, and the
  marker must be removed. That way the contract can't drift silently.

## Step 6: what already works (verified)

| Check | Evidence |
|---|---|
| Content reaches the pipeline; only the brand's approved sources are retrieved | `test_all_three_verdicts_reach_the_review_with_provenance_and_routing`, `test_security_controls.py` |
| Evidence provenance (source id, version id, version number, verbatim quote) | same test |
| Corrections traceable to cited evidence; re-verified before being offered | `test_a_correction_is_traceable_to_the_cited_evidence` |
| Uncertain claims go to a person (`requires_human_review`, review `needs_human_review`) | integration tests above |
| Invalid, malformed or fabricated output never becomes a verdict | `test_invalid_or_malformed_verification_output_is_unverified_never_supported`, `test_a_fabricated_quote_is_refused_by_the_guard_and_the_backend` |
| Provider failures are `unverified` / `engine_error` and logged | `test_a_provider_failure_is_never_a_verdict_and_is_logged` |
| One failed claim doesn't affect the others | `test_one_failing_claim_leaves_the_other_claims_intact` |

## Step 6: gaps (owner: Darsh)

All line numbers refer to `services/api/src/inkloom_api/engine/pipeline.py` at the time of writing.

**Gap 1: conflicting sources.** The engine sets `ClaimResult.conflicting_sources` when approved
documents disagree. The backend maps every NOT_ENOUGH_EVIDENCE to `unverified` (line ~396).
Change:
```text
status = VerificationStatus.CONFLICTING_SOURCES if (verdict is Verdict.NOT_ENOUGH_EVIDENCE
         and result.conflicting_sources) else _STATUS_FOR_VERDICT[verdict]
```
Keep `requires_human_review=True`. Test: remove the xfail from
`test_gap1_conflicting_approved_sources_are_reported_as_conflicting_sources`.

**Gap 2: safer wording stored as a correction.** Line ~366,
`proposal = softening if softening is not None else result.correction`, stores the softened
wording, which isn't evidence-backed, in `suggested_correction`. The agreed contract keeps them apart.
- **Correction:** `suggested_correction` comes only from `result.correction`.
- **New column:** `findings.safer_wording TEXT NULL` (migration), shown in `FindingOut` and
  `contract/schemas/finding.schema.json`. `softening_guard.py` keeps checking it.
- **UI label (Chahit):** "Safer wording, not evidence-backed".

Test: remove the xfail from `test_gap2_safer_wording_is_kept_out_of_suggested_correction`.

**Gap 3: rule findings.** Call
`inkloom_verify.rules.evaluate_rules(content_version.text, brand_rules)` in `run_review`, before
extraction at line ~159. It's deterministic, makes no model call, and runs even without a provider.
Store each finding via `inkloom_verify.integration.rule_finding_fields`. Full contract, storage
proposal and cache-key note: [RULES_HANDOFF.md](RULES_HANDOFF.md). Test: remove the xfail from
`test_gap3_rule_findings_appear_in_reviews`.

## Step 7: AI support for the review workflow

### Softening (built in the engine)
`ClaimSoftener.soften(result, content, locked_phrases=())` behaves as follows:
- **Scope:** NOT_ENOUGH_EVIDENCE claims only.
- **Content:** it removes or softens; it never adds facts, numbers, names or rankings.
- **Status:** the finding stays unverified.
- **Locks:** the result is refused if it would remove locked text.
- **Storage:** see gap 2.

### Intent-lock (engine enforcement built; server enforcement is Darsh's)
Definition (DESIGN.md §21 D and §22): *"protected spans cannot change in a suggestion"*. Today the
locks are exact phrases kept only in the browser (`lib/additions/locks.ts`), and the server neither
stores nor enforces them.

The engine now enforces it **deterministically**, with no prompt instruction involved
(`inkloom_verify.intent_lock`):
- **Corrections:** `ClaimCorrector.correct(result, content, locked_phrases)` refuses a correction
  that would remove a locked phrase. Issue `intent_lock`; the verdict stays CONTRADICTED; a person
  decides; no extra model call is made.
- **Softening:** `ClaimSoftener.soften(..., locked_phrases)` refuses the same way.
- **Engine API:** `VerificationRequest.locked_phrases` does the same through the engine's own
  pipeline.
- **Server checks:** `intent_lock_violations(original, revised, locks)` and
  `check_replacement(text, start, end, replacement, locks)` let the server run the same check.
  Semantics: exact, case-sensitive phrases (like the frontend), and a phrase occurring n times must
  still occur n times.
- **Tests:** `tests/test_intent_lock.py` (19).

Darsh, for server-side enforcement:
1. **Store locks** per content version, e.g. `content_versions.locked_phrases JSONB NOT NULL
   DEFAULT '[]'`, validated with `intent_lock.validate_locks`, with an endpoint to set them.
2. **Pass them in:** `corrector.correct(result, content, locks)` at line ~221 and
   `softener.soften(result, content, locks)` at line ~246.
3. **Re-check before storing** any suggestion: `check_replacement(...)` on the claim span. The
   backend never trusts the engine; that's the existing principle.
4. **Hand-written edits are a product decision.** The spec covers *suggestions* only. Recommended:
   warn rather than block when a new version drops a locked phrase (`intent_lock_violations`).

Chahit: read and write locks through the API instead of `localStorage`.

### Per-finding Dismiss (not built; owner: Darsh and Chahit)
DESIGN.md §21 has `Decision.action: accept | edit | dismiss | escalate` per finding. The backend
has review-level decisions only. The engine needs no change: findings already carry stable ids
(`finding_id`, plus `engine_claim_id` for claims and `rule_id` for rule findings). Requirements
from the engine side:
- **Never touch the finding.** Dismissing must not change `verification_status`, `evidence` or the
  explanation. Record it as a separate decision row (finding id, action, note, who, when) plus an
  audit event.
- **Dismissed is not proven true.** The UI must say "Dismissed by …", never "supported" or
  "verified". A dismissed `contradicted` finding remains contradicted in the record.
- **Re-runs:** a new review produces new findings. Whether a dismissal carries over (matched on
  `engine_claim_id` or `rule_id` plus the text) is a product decision.

### Comments on findings (not built; README roadmap item 4)
The engine provides the identifiers and context a comment thread needs: `finding_id`, the span,
`original_text`, `rule_id`/`engine_claim_id`, and the evidence quote. Storage and API belong to
Darsh, the UI to Chahit. No engine change is needed.
