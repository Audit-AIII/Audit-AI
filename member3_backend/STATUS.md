# Member 3 (backend) status

Last updated: 2026-10-23. Read `00_CONTEXT.md` for the product/governance rules this all enforces.

## One-line summary

Phases 1-7 are built and verified against a real database, including live end-to-end runs
through real HTTP calls. Phase 5 is fully done, tasks 1 and 5-8 both: the multi-provider
fallback chain, result cache, idempotency keys, per-user/per-org rate limiting, and
confidential-source routing (cloud providers never even constructed for a confidential source).
Phase 8 task 1 (the 12-test checklist) is now also fully done — the last two gaps (concurrent
reviewer actions, audit-on-rejection) closed this session, including a real lost-update bug
found and fixed along the way (see "Phase 8 task 1 audit" below). 84 tests pass against the real
Postgres database. Also done this session: task 2 (`scripts/seed.py`), task 3
(`scripts/smoke_test.py` — both run live, see "Phase 8 tasks 2-3" below), task 4 (README.md
refresh), the DISCLOSURE.md part of task 5, and task 8 (secret scan — clean, see "Phase 8 task 8
audit" below). Left: deploy (task 6, needs a separate check-in - real external infra), the
fallback demo path / recorded backup video (task 7).

## Phase-by-phase status

| Phase | Status | Verified how |
|---|---|---|
| 1. Foundation and contract | Done | Real DB: migration up/down/up, all tables, all tests |
| 2. Auth and tenant scoping | Done | Real DB: login, token, revoked-membership, cross-tenant tests |
| 3. Vertical slice | Done | Real DB + real server: submit → fetch, stub path and real-engine path both exercised live |
| 4. Evidence validation and sources | Done | Real DB + real server: validator unit tests, real file uploads (.txt/.pdf/.docx) through the live endpoint, approve/list/reject paths all hit live |
| 5. Provider adapter (task 1) | Done | Mocked unit tests (429/timeout/malformed/all-down) plus a live run against real Gemini/OpenRouter — correct fallback/failure behavior confirmed. No successful real-provider finding has been captured in a test (would need a live API key committed to CI, which we deliberately don't do), but the stub-labelled path and the all-fail path are both fully proven |
| 5. Cache, idempotency, rate limits, confidential routing (tasks 5-8) | Done | Real DB, 3 new end-to-end tests: duplicate `Idempotency-Key` replays with zero extra LLM calls and one job row; byte-identical content in two organisations produces two cache entries and two real analyses, never a shared hit; a confidential source's review never even constructs a cloud provider builder, and `external_call_log` has zero rows for it. Plus 2 fixes to real pre-existing gaps found while wiring this (see below) |
| 6. Versioning, approval, audit | Done | Real DB: tests pass. Live, end to end, through real HTTP calls: submit → request-changes → edit to a new version → rerun → approve → open audit history — exactly phase 6's own "done when" bar |
| 7. Source lifecycle: manual withdraw (tasks 1-3, 5-6) | Done | Real DB, including tenant isolation and audit-event coverage |
| 7. Source lifecycle: automatic section diff (task 4) | Done | Real DB. Empirically verified chunk-boundary behavior before writing the test, not guessed |
| 7. Source conflict detection (task 7, marked Optional in the doc) | Not started, not requested | — |
| 8. Tests, seed, README, deploy | Tasks 1-5 and 8 done; task 6 (deploy) and task 7 (fallback demo path) not started | See "Phase 8 task 1 audit" and "Phase 8 tasks 2-3" below |
| 9. Stretch | Not started (gated on a tagged release existing) | — |

All 84 tests pass in one command: `cd services/api && set -a; source .env; set +a; ./.venv/Scripts/python.exe -m pytest -q`.

## Phase 8 task 1 audit (the test checklist, not the rest of Phase 8)

Of the 12 required tests the phase doc lists, checked against what exists today:

| Required test | Status |
|---|---|
| Org A cannot read/mutate org B's review, source, content or audit records | Covered (`test_tenant_scoping.py`, `test_cross_tenant_content_and_audit.py`) |
| Changing `organisation_id` in a request body grants nothing | Partially N/A: no route in this API accepts `organisation_id` as a body field at all (it's always derived from the authenticated membership) — the closest real attack surface, a query-string override, is covered (`test_query_string_organisation_override_is_ignored`) |
| Revoked membership loses access | Covered (Phase 2) |
| Invalid transitions and stale-version approvals are rejected | Covered (`test_approval_rules.py`, `test_content_versioning.py`) |
| Non-approver gets a safe response, with an audit event where appropriate | Covered: the safe-403 half (`test_post_reviews_requires_submit_permission`); and **newly covered this session**, `test_reviewer_cannot_approve_but_can_request_changes` now asserts a denied attempt writes zero audit events (intentional - stopped by auth before any state change) while the actual recorded decision writes exactly one |
| Engine output with unknown source IDs, wrong-brand evidence, quote not in source, or invalid schema is rejected | Covered (`test_evidence_validator.py`, `test_pipeline_robustness.py`) |
| Provider 429, timeout, invalid JSON and all-providers-down never produce an approved state | Covered (`test_fallback_provider.py` at the adapter level, `test_provider_failure_never_approved.py` end to end) |
| Duplicate idempotency key creates one job and one LLM call | **Newly covered this session** (`test_phase5_cache_idempotency_confidential.py`) |
| Same content in two organisations never shares a cache entry | **Newly covered this session** (same file) |
| A confidential source produces no external call in the log | **Newly covered this session** (same file) |
| Concurrent reviewer actions leave state and audit trail consistent | **Newly covered this session**, and a real bug fixed in the process — see the update note above (`test_truly_concurrent_decisions_the_db_lock_serializes_them`) |
| Edit after approval creates a new version that is not approved | Covered (Phase 6 versioning tests) |

**Update, this session**: both remaining gaps are now closed.

- **Concurrent reviewer actions**: while writing a true (not just sequential) concurrency test, found a real lost-update bug — `_latest_review_or_404` (`routers/content_versions.py`) fetched the review with a plain `SELECT`, no lock, so two genuinely overlapping transactions could both pass `ensure_decidable`/`check_approve_guards` and both call `record_decision`, producing two contradictory `ApprovalEvent`/`AuditEvent` rows instead of a safe 409 for the loser. Fixed with `.with_for_update()` so the second transaction blocks until the first commits, then correctly re-reads the new status and is rejected. Proved the fix matters by removing it and watching the new test fail (`'A': ('ok', 'approved'), 'B': ('ok', 'rejected')` — both "succeeded"), then restoring it and re-running 3x clean. New test: `test_truly_concurrent_decisions_the_db_lock_serializes_them` — uses `threading.Event`s to pin the timing explicitly (a bare `threading.Barrier` wasn't enough; the race didn't reproduce reliably on wall-clock timing alone), not a copy of the route logic but the exact functions the HTTP routes call.
- **Audit-on-rejection**: `test_reviewer_cannot_approve_but_can_request_changes` now asserts explicitly that a 403 permission denial writes zero `AuditEvent` rows (stopped by auth before any state change — intentional, not an oversight) and that the actual recorded decision (`request-changes`) writes exactly one.

## Phase 8 tasks 2-3: seed script and smoke test — both run live, not just written

`scripts/seed.py` — one demo organisation, a brand with two approved sources (text copied
verbatim from Member 2's own eval fixture, `services/verification/eval/dataset.jsonl`, so demo
findings are checked against text their eval suite already exercises, not an invented brand),
five users (one per membership role, shared demo password, printed at the end), and four demo
content items each run through a real `start_review` call: a terminology violation, a
contradicted claim, an unsupported promise, and a prompt-injection sample. Idempotent (checked
by running it twice - second run no-ops cleanly). Labelled `[SEEDED]` throughout; synthetic
content only. **Ran it against the real database** - it works, but the four demo reviews
currently land on `failed` or `needs_human_review` rather than a clean real finding, because
the configured `OPENROUTER` model (`nvidia/nemotron-3.5-lightning:free`) 404s and no other
provider in `.env` is currently working either - the same free-tier flakiness already
documented elsewhere in this file, not a bug in the seed script. Fix by picking a current,
actually-live model id (OpenRouter/Gemini/Groq) or pointing `OLLAMA_*` at a local model for a
reliable, non-cloud fallback.

`scripts/smoke_test.py` — drives the full phase-8-task-3 path over real HTTP against a running
server: create review → fetch findings → request changes → create new version → approve →
inspect audit history. **Ran it twice**: once against the real configured providers (failed to
reach a decidable state after 3 attempts, same free-tier issue as above - the script's own
retry-and-report behavior, not a crash); once with the server restarted on a minimal
provider-free `.env` (forcing stub mode, since `main.py` reloads `.env` on every process start
so unsetting shell env vars alone doesn't work) - passed clean end to end, confirming the
script's actual logic is correct independent of provider flakiness.

Found a real, pre-existing contract gap while writing it: `ReviewOut` (what `POST /api/reviews`
and `GET /api/reviews/{id}` return) never exposes `content_item_id`, only
`content_version_id` - but creating a new version (`POST /api/content/{content_item_id}
/versions`) needs the item id, and nothing in this flow's responses carries it. The test suite
already had the identical workaround (`test_approval_rejected_when_stale`, a direct DB query,
with a comment saying exactly this) - this was not a new discovery, just now written up and
also worked around the same way in the smoke test. Worth raising with Member 1 if their frontend
hits the same wall; not fixed here since changing a shared response shape needs the team's
sign-off per `00_CONTEXT.md`.

Both scripts wipe when `test_migrations.py`'s downgrade/upgrade cycle runs (same known
limitation as hand-seeded data always had) - reseed after a full `pytest` run.

## Phase 8 task 8 audit: secret scan

Scanned (not just the API's own tree - the whole repo, including Member 1's frontend under
`audit-ai-final/frontend/` and Member 2's `services/verification/`, read-only, no edits made to
either per `00_CONTEXT.md`):
- Full git history (`git log --all -p`) for API-key-shaped strings (Gemini `AIza...`, OpenAI
  `sk-...`, Groq `gsk_...`, AWS `AKIA...`, PEM private key headers) and for a filled-in
  `OPENROUTER_API_KEY=`/`GEMINI_API_KEY=`/`GROQ_API_KEY=`/`AUTH_SECRET_KEY=` ever being committed.
  One hit, and it's not a secret: a README code example literally reading
  `AUTH_SECRET_KEY=test-secret`, a placeholder in a `pytest` command line.
- The current tree for the same patterns, plus a repo-wide sweep for any tracked file actually
  named `.env` (only `.env.example` files are tracked, everywhere).
- The frontend tree for a committed `.env*`, `.next/` build output, or `node_modules/` - none
  tracked.

Clean. Nothing further to report for this task.

84 tests pass (was 83). Also closed a real Phase 5 task 11 gap found while here: `DISCLOSURE.md` still described only Phase 1 (Postgres only) — updated to disclose the Gemini/Groq/OpenRouter/Ollama fallback chain, confidential-source routing, and the in-memory cache/idempotency/rate-limit layers.

The rest of Phase 8 (seed script, smoke test, README refresh, deploy, fallback demo path, secret-scan) has not been started.

## Phase 7: what's actually built

Routes: `POST /api/brands/{id}/sources/{source_id}/withdraw` (manual, task 3) and `POST
/api/brands/{id}/sources/{source_id}/versions` (new version of an existing source, automatic
diff, task 4).

- `source_lifecycle.py` — `dependent_content_version_ids` (task 2's query, a plain join through
  `EvidenceLink -> Finding -> Review -> ContentVersion`, no new columns needed since task 1's
  "keep every version" was already true from Phase 1/4), `withdraw_source` (flips every
  currently-*approved* dependent unconditionally), `apply_new_version_diff` (flips only a
  dependent whose evidence cited a section that didn't survive into the new version).
- `section_diff.py` — reuses Member 2's `chunking.py` read-only (no edits to their code, per
  your instruction) to define "section" as exactly the same unit `BM25Retriever` already
  chunks documents into. Confirmed task 6 ("verify the approval guard covers `source_changed`")
  needed no new code - the existing Phase 6 state machine already rejects it correctly.
- Schema: `source_versions.section_hashes` (every section's hash, computed at upload time),
  `evidence_links.cited_section_hash` (which section a citation came from, computed when the
  pipeline writes the evidence row). Both nullable/backward-compatible for rows written before
  this existed.
- Found and fixed a second real pre-existing gap while testing this: `evidence_links.source_id`
  / `source_version_id` had no `ON DELETE` rule at all, so any hard-delete of a brand source
  (never done by the app today, but a real future risk) would crash with a foreign-key
  violation. Fixed to `SET NULL` (migration 0004).
- Before writing the section-diff test, empirically ran `chunk_document` against real sample
  text rather than guessing chunk boundaries - confirmed that editing one section shifts
  character offsets in a later, untouched section without changing its hash, which is exactly
  the property the whole feature depends on.
- 6 new tests (5 manual-withdraw, 1 section-diff), all passing against the real DB.

## Phase 6: what's actually built

Routes: `POST /api/content/{id}/versions` (creates a version AND runs a review on it in one
call — confirmed with the team), `POST /api/reviews/{id}/rerun`, `POST
/api/content-versions/{id}/approve`, `POST /api/content-versions/{id}/request-changes`, `GET
/api/content/{id}/history`.

- `approval_rules.py` — the pure state machine (no DB): a review is decidable only from
  `completed`/`needs_human_review`; every other state is a safe 409, never a 403.
- `approval_service.py` — the DB-aware guards task 4 lists: not-decidable, stale
  (`current_version_id != reviewed_version_id`), and a cited source no longer the brand's
  approved version (anticipates Phase 7's `source_changed`, verified now rather than later).
- `review_runner.py` — extracted the "build corpus, run pipeline" logic shared by submit,
  new-version, and rerun, so all three behave identically.
- Schema additions: `content_items.brand_profile_id` (a real gap found while building this —
  Phase 3 never persisted which brand a piece of content belongs to, so rerun/new-version had
  no way to know which sources to check against) and `content_versions.is_current`, with a
  Postgres partial unique index guaranteeing only one current version per content item at the
  database level, not just in application code.
- Permission split: `approve` route requires the `approve` permission (`approver`/`admin`
  only); `request-changes` requires the lighter `review` permission (`reviewer` too) — rejecting
  is always safe to allow even for a role that can't give final sign-off.
- Audit events now cover: submit, rerun, edit (new version), approve, reject, request-changes.
  (Source approval was already covered in Phase 4.)

## Phase 5 provider adapter: what's actually built

`services/api/src/inkloom_api/engine/providers/`:
- `gemini.py`, `groq.py`, `ollama.py` — one class each, all satisfying Member 2's `LLMProvider`
  protocol. No changes to `services/verification` at all.
- `retry.py` — shared bounded retry (429/5xx/timeout only), used by all three above.
- `fallback.py` — `FallbackProvider`: tries Gemini → Groq → OpenRouter `:free` → Ollama, in that
  order, falling through on **any** `ProviderError` (generalized from the 403/404/429 examples
  that exposed the original gap). Logs every real attempt via an `on_attempt` hook wired to
  `external_call_log` (provider, model, latency, error code — never content or keys).
- `engine/provider.py`'s `build_provider(confidential=...)` — when `confidential=True`, the
  cloud builders (Gemini/Groq/OpenRouter) are never even in the list handed to
  `FallbackProvider`, not merely skipped at call time. Proven directly in the new test by making
  the cloud builders raise `AssertionError` if ever invoked.

Two real bugs found and fixed while testing this live, beyond the original design:
1. The Gemini SDK (`google-genai`) has its own built-in retry, enabled by default for 5xx/429.
   It was compounding with this adapter's own retry — two independent retry loops multiplying
   delay instead of adding it, which hung a single transient 503 for over a minute. Fixed by
   disabling the SDK's internal retry (`attempts=1`) so `retry.py` is the only layer.
2. My first two guesses at a Gemini model id (`gemini-2.0-flash`, `gemini-2.5-flash`) are both
   fully retired for new API keys. Found the actual current id (`gemini-3.8-flash`) by listing
   the real account's available models rather than guessing a third time.

**On the "no successful live AI finding yet" note from earlier**: still true as of this update
— the free tiers of the configured cloud providers have been unreliable enough during testing
that no live run has produced a real `supported`/`contradicted` finding end to end. Every
*failure* mode (timeout, rate limit, malformed output, all-down) is fully proven, live and in
mocked tests; only the success path through a real model has not been captured. This does not
block Phase 5 being done — the phase's job was the adapter and its safety properties, not a
guaranteed-available free model.

## Phase 5 tasks 5-8: what's actually built

`services/api/src/inkloom_api/`:
- `result_cache.py` — `compute_cache_key` hashes `{organisation_id, content_version.text_sha256,
  sorted source fingerprints, engine CONTRACT_VERSION}`; `organisation_id` is mandatory in the
  key specifically so two tenants never share a cache entry, even for byte-identical content
  against byte-identical sources. Only a genuine completed analysis is ever cached — never a
  stub or a provider/corpus failure, since those are transient facts about one run, not durable
  facts about the content.
- `idempotency.py` — `Idempotency-Key` header support on both `POST /api/reviews` and
  `POST /api/reviews/{id}/rerun`: replays the stored response byte-for-byte on a repeat with the
  same key and body, and returns a safe 409 if the same key is reused with a different body.
- `rate_limit.py` — in-memory fixed-window limiter, per user and per organisation, on
  `POST /api/reviews`. Explicitly single-process only (no Redis) — fine for this project's scale,
  documented as a known limitation rather than hidden.
- `review_runner.py` / `engine/pipeline.py` — a review is `confidential` if *any* source in its
  corpus is marked confidential; `run_review` then only ever builds the Ollama-only provider
  chain for it, and checks the cache before touching any provider at all (so a cache hit, even
  for a confidential review, makes zero external calls).

Two more real pre-existing gaps found and fixed while wiring this (same bug class as the
`evidence_links` fix from Phase 7, migration 0004): `external_call_log.review_id` and
`result_cache.review_id` had no `ON DELETE` rule at all, so deleting a review (or an
organisation, cascading to its reviews) that already had a logged call or a cache row pointing
at it crashed with a foreign-key violation instead of degrading gracefully. Fixed to `SET NULL`
in migration 0007 — both rows are durable operational/audit records that should outlive the
review they happened to reference.

3 new end-to-end tests (`test_phase5_cache_idempotency_confidential.py`), all passing against
the real DB, using Member 2's own `ScriptedProvider` test double to count real LLM calls rather
than guessing at internals.

## What's left from you (please work through these)

1. **Review and confirm before I commit.** Nothing from Phase 5 onward has been committed yet.
   Everything through Phase 4 is already committed (your own commit `3dd3c59 "phase4"`); Phase
   5 (both the provider adapter and tasks 5-8), Phase 6, Phase 7, and this session's Phase 8
   work (task-1 closure, seed script, smoke test, README refresh, DISCLOSURE.md update, secret
   scan) are all new, uncommitted work, plus the two `ON DELETE` migrations (0004, 0007).

2. **Pick a working free-tier model, or point at local Ollama.** The seed script and smoke test
   both ran live against the real database this session and work correctly, but the four demo
   reviews land on `failed`/`needs_human_review` rather than a clean finding because the
   configured `OPENROUTER` model 404s and nothing else in `.env` is currently reachable either
   — see "Phase 8 tasks 2-3" above. This has been a recurring issue across sessions (two earlier
   Gemini model-id guesses were also already retired); worth just sitting down with each
   provider's live model list once rather than guessing a third/fourth time.

3. **Decide what's next**: deploy (task 6 — real external infra, I'll check in separately) and
   the fallback demo path / recorded backup video (task 7) are what's left of Phase 8.

4. **Decide whether to flag the OpenRouter `require_parameters: true` issue to Member 2.** My
   adapter already works around it (falls through to the next provider regardless), so this is
   not blocking — but `OpenRouterProvider`'s *own* internal retry across multiple configured
   OpenRouter models still stops immediately on this error. Worth a heads-up to them, or not —
   your call, per "ask Member 2 via me before touching anything in services/verification."

5. **Decide whether to flag the `ReviewOut`-never-exposes-`content_item_id` gap to Member 1.**
   Found (again — the test suite already had the same workaround) while writing the smoke test;
   see "Phase 8 tasks 2-3" above. Not blocking (both the tests and the smoke test work around it
   with a direct DB query), but their frontend will hit the same wall on the Correction Editor
   screen unless it already has another way to know the content item id.

6. **A reminder, not new**: every full `pytest` run (specifically `test_migrations.py`'s
   downgrade-to-`base`-then-upgrade cycle) wipes all data, including seeded demo data. Reseed
   with `services/api/scripts/seed.py` after running the full suite if you want persistent demo
   data between sessions.

## Known limitations (not bugs, just not done)

- The rate limiter and idempotency replay cache are both in-process memory — correct for a
  single-process demo deployment, but reset on restart and not shared across multiple worker
  processes. Documented in `rate_limit.py`'s own docstring, not hidden.
- No deploy yet, no fallback demo path / recorded backup video yet (Phase 8 tasks 6-7).
- The approval guard's "source superseded" check (Phase 6 task 4) looks at the *latest* version
  of each cited brand source and its current status — it does not yet distinguish a source that
  was superseded for an unrelated reason from one whose *cited section specifically* changed
  (that finer-grained diff is explicitly Phase 7's job, task 4).
- `GEMINI_MODEL`/`OPENROUTER` currently have no verified-working value in this environment's
  `.env` — see item 2 under "What's left from you" above. Not for lack of trying: three
  concrete guesses across sessions (two Gemini model ids, one OpenRouter model id) have all
  turned out already retired or 404ing.
- `ReviewOut` never exposes `content_item_id` — see item 5 under "What's left from you" above.
