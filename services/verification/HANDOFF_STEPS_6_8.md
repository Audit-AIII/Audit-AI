# Steps 6–7: engine ↔ backend integration, and the AI side of the review workflow

**From:** Krish (Member 2, engine) · **To:** Darsh (backend), Chahit (frontend) · 2026-10-24

This lists what the engine provides, the gaps found when testing it end to end through the backend,
and their status. **All three backend gaps and the Step 7 features are now closed on `main`**:
Darsh's commits `df6b2ae` (gaps 1 and 2), the brand-rules work (gap 3) and `021637b` (Intent-lock,
Dismiss, comments). Each was re-verified against the real backend on 2026-10-24 (below).

**How it was tested:** `services/api/tests/test_engine_integration.py`. It runs real routes, real
Postgres, the real engine and the backend's own evidence check, with only the model scripted. As of
2026-10-24 it has **16 tests, all passing, and no expected failures left**. The three
`test_gap*` tests used to be strict expected failures; Darsh removed each marker when he fixed the
gap.

## Step 6: what works (verified)

| Check | Evidence |
|---|---|
| Content reaches the pipeline; only the brand's approved sources are retrieved | `test_all_three_verdicts_reach_the_review_with_provenance_and_routing`, `test_security_controls.py` |
| Evidence provenance (source id, version id, version number, verbatim quote) | same test |
| Corrections traceable to cited evidence; re-verified before being offered | `test_a_correction_is_traceable_to_the_cited_evidence` |
| Uncertain claims go to a person (`requires_human_review`, review `needs_human_review`) | integration tests above |
| Invalid, malformed or fabricated output never becomes a verdict | `test_invalid_or_malformed_verification_output_is_unverified_never_supported`, `test_a_fabricated_quote_is_refused_by_the_guard_and_the_backend` |
| Provider failures are `unverified` / `engine_error` and logged | `test_a_provider_failure_is_never_a_verdict_and_is_logged` |
| One failed claim doesn't affect the others | `test_one_failing_claim_leaves_the_other_claims_intact` |

## Step 6: gaps (all closed, verified 2026-10-24)

| Gap | Was | Now | Test (passes, no xfail) |
|---|---|---|---|
| 1. Conflicting sources | `ClaimResult.conflicting_sources` was mapped to `unverified` | Mapped to `verification_status` `conflicting_sources`, still `requires_human_review` (`df6b2ae`) | `test_gap1_conflicting_approved_sources_are_reported_as_conflicting_sources` |
| 2. Safer wording | The softened wording, which isn't evidence-backed, was stored in `suggested_correction` | Stored in its own `safer_wording` field; `suggested_correction` comes only from evidence-backed corrections (`df6b2ae`). The UI labels it "Safer wording, not evidence-backed" (`53ef611`) | `test_gap2_safer_wording_is_kept_out_of_suggested_correction` |
| 3. Rule findings | `rules.evaluate_rules` wasn't run in reviews | The backend runs `evaluate_rules` on every review and stores findings via `integration.rule_finding_fields` (see [RULES_HANDOFF.md](RULES_HANDOFF.md) §7) | `test_gap3_rule_findings_appear_in_reviews` |

For Darsh: the comments inside the gap 1 and gap 2 tests still say "fails today". They're stale now
and can be removed.

## Step 7: AI support for the review workflow

### Softening (engine) and safer wording (backend and frontend): done
`ClaimSoftener.soften(result, content, locked_phrases=())` behaves as follows:
- **Scope:** NOT_ENOUGH_EVIDENCE claims only.
- **Content:** it removes or softens; it never adds facts, numbers, names or rankings.
- **Status:** the finding stays unverified.
- **Locks:** the result is refused if it would remove locked text.

The backend stores the result in `safer_wording` (gap 2).

### Intent-lock: done (engine and server)
Definition (DESIGN.md §21 D and §22): *"protected spans cannot change in a suggestion"*. Locks are
exact, case-sensitive phrases, and a phrase occurring n times must still occur n times.

- **Engine** (`inkloom_verify.intent_lock`, 19 tests in `tests/test_intent_lock.py`):
  - `ClaimCorrector.correct(..., locked_phrases)` refuses a lock-breaking correction (issue
    `intent_lock`; the verdict is unchanged; a person decides).
  - `ClaimSoftener.soften(..., locked_phrases)` refuses the same way.
  - `VerificationRequest.locked_phrases` does the same through the engine's own pipeline.
  - `check_replacement` and `intent_lock_violations` let a server re-check anything.
- **Backend** (`021637b`):
  - stores `content_versions.locked_phrases`, validated with `validate_locks`;
  - serves `GET`/`PUT /api/content-versions/{id}/locks`;
  - passes locks to the corrector and softener, and re-checks every stored suggestion with
    `check_replacement` (`intent_lock_guard.py`);
  - carries locks over to new versions, and includes them in the cache key.

  Tests: `services/api/tests/test_intent_lock_dismiss_comments.py` (10 passed on 2026-10-24).

### Per-finding Dismiss: done (backend)
`POST /api/findings/{id}/dismiss` and `.../restore` record a decision without touching the finding.
`test_dismiss_and_restore_never_touch_the_finding` asserts that `verification_status`, evidence,
explanation, suggestion, severity and category are unchanged, so a dismissed contradicted finding
is still contradicted, never "supported". Concurrent dismisses record one decision.

### Comments on findings: done (backend)
`GET`/`POST /api/findings/{id}/comments`, scoped to the account. The engine provides the
identifiers and context a thread needs (`finding_id`, span, `original_text`,
`rule_id`/`engine_claim_id`, evidence quote).

## Still open from the engine side
- **No live model accuracy has been established.** See EVAL.md, "Live evaluation status".
- **Image, media and colour checks on uploaded files:** see the proposal in
  [RULES_HANDOFF.md](RULES_HANDOFF.md) §5.
