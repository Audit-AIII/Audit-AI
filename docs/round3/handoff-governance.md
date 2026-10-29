# Handoff to Darsh: governance and risk routing (Round 3 step 10A)

From Krish, 2026-10-29. **Not sent yet.** This is a contribution, not ownership: the backend,
routing and governance are Darsh's. Everything below was checked against branch
`krish/round3-reconcile` (commit `e9055a2`).

## What I found already done (Darsh's work, with evidence)

The runbook (step 10A) expected to find routing on `verdict != SUPPORTED` only. That gap is
closed.

| Runbook item | Status | Evidence |
|---|---|---|
| 1. Signal table: verdict and `review_reasons` → risk tier | **Done by Darsh** | `services/api/src/inkloom_api/risk_policy.py` (commit `47ce198`, "Phase 4: risk-based routing"), which follows `contracts.md` §19. The backend applies the engine's decision policy per claim (`engine/pipeline.py`, `_with_decision_policy`). Tests: `services/api/tests/test_risk_routing.py`. |
| 2. Unknown guard reasons must not crash anything | **Done by Darsh** | `risk_policy.py` routes any unknown status or review reason to medium (`unknown_signal`) and passes it through. Tests cover it: `test_section_19_mapping` has `property_mismatch`, `unsupported_clause` and an invented code; `test_unknown_statuses_and_reason_codes_route_conservatively` runs it through the database. |
| 3. ERROR is never SUPPORTED and never auto-approved | **Partly covered** (see open question 2) | `services/api/tests/test_provider_failure_never_approved.py`: when every provider fails, the review is `failed` and approve answers 409. `test_section_19_mapping` routes an `engine_error` finding to medium. |
| 4. Real engine output as sample data for the demo queue | **Not available** | No live full-pipeline run exists yet (runbook step 07), so there are no `cases.jsonl` files to offer. |

**Evidence that it runs:** CI on `e9055a2` passed "3. Backend test suite (real PostgreSQL)". I
didn't run the backend tests locally: my `services/api/.env` points at a dev database and holds
real provider keys, and CI uses neither.

## What reaches the backend from the engine (for reference)

- Per claim: `verdict`, `requires_human_review`, `review_reasons` (`contradicted`,
  `not_enough_evidence`, `error`, `weak_evidence`, `below_policy_strength`,
  `compound_under_cited`) and `evidence_strength`.
- **Guard reasons do not reach the backend's stored findings.** `property_mismatch` and
  `unsupported_clause` live in the engine report's `citation_guard.rejected[]`. When the guard
  refuses a SUPPORTED answer, the claim arrives as `NOT_ENOUGH_EVIDENCE` with
  `review_reasons: ["not_enough_evidence"]`, and the backend stores it as `unverified` (medium
  risk). The `unknown_signal` tests are therefore defensive. Keep them.
- **One behaviour changed on `krish/round3-reconcile` that your tests saw.** A compound claim
  whose one quote leaves a part uncovered is now `unverified`, no longer
  `supported` + `compound_under_cited`. I updated `services/api/tests/test_decision_policy.py`
  for it (commit `e9055a2`): the old case asserts the new status, and a new case keeps
  `compound_under_cited` for a compound claim one quote fully covers. **Please review that
  change**, since it's in your test suite.

## Open questions for Darsh (dated 2026-10-29, no reply yet)

1. **Approve the two new guard reason codes and the test change above** before PR
   `krish/round3-reconcile` → main merges. Your 2026-10-28 reply (contracts.md §22) said the
   codes are safe; the test change is new.
2. **ERROR in the approval tests.** The provider-failure test covers "all providers fail". Is
   there a database test for a *partial* failure, where one claim is `ERROR` (`engine_error`,
   medium) and the others are clean? It should check the draft can't go to an approver only and
   the author can't approve it. I couldn't find one in `test_self_approval.py`,
   `test_approval_rules.py`, `test_e2e_governance.py` or `test_governance_roles.py`. If it's
   missing, I can draft it for you to accept or change.
3. **Scorecard contract, still awaiting you** (contracts.md §23 items 1–3): the
   `/api/evaluations/latest` shape, removing the Run button from the main flow, and the
   `per_check` ratios.
4. **PR #25** (`krish/round3-prior-work` merged into main): the team's decision on whether it
   stays, given it was marked reference-only.
5. **Demo data:** when step 07 produces live runs, do you want their `cases.jsonl` loaded as
   sample review data for the risk-tiered queue?
