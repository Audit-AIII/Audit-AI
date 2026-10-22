# Member 3 (backend) status

Last updated: 2026-10-23. Read `00_CONTEXT.md` for the product/governance rules this all enforces.

## One-line summary

Phases 1-4 and Phase 6 are built and verified against a real database, including live
end-to-end runs through real HTTP calls. Phase 5's provider adapter (task 1, the multi-provider
fallback chain) is built and verified with mocks and run live against real external services —
it behaves correctly under failure, but no successful real AI finding has happened yet. Phase 5
tasks 5-8 (cache, idempotency, rate limits, confidential routing) are not started. Phase 7
onward is not started.

## Phase-by-phase status

| Phase | Status | Verified how |
|---|---|---|
| 1. Foundation and contract | Done | Real DB: migration up/down/up, all tables, all tests |
| 2. Auth and tenant scoping | Done | Real DB: login, token, revoked-membership, cross-tenant tests |
| 3. Vertical slice | Done | Real DB + real server: submit → fetch, stub path and real-engine path both exercised live |
| 4. Evidence validation and sources | Done | Real DB + real server: validator unit tests, real file uploads (.txt/.pdf/.docx) through the live endpoint, approve/list/reject paths all hit live |
| 5. Provider adapter (task 1 only) | Built, partially verified | 12 mocked unit tests pass (429/timeout/malformed/all-down). Run live against real Gemini/OpenRouter — correct fallback/failure behavior confirmed, but **no successful real finding yet** |
| 5. Cache, idempotency, rate limits, confidential routing (tasks 5-8) | Not started | — |
| 6. Versioning, approval, audit | Done | Real DB: 71 tests pass. Live, end to end, through real HTTP calls: submit → request-changes → edit to a new version → rerun → approve → open audit history — exactly phase 6's own "done when" bar |
| 7. Source lifecycle / InkWatch | Not started | — |
| 8. Tests, seed, README, deploy | Not started (API.md exists; no seed script) | — |
| 9. Stretch | Not started (gated on a tagged release existing) | — |

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

Two real bugs found and fixed while testing this live, beyond the original design:
1. The Gemini SDK (`google-genai`) has its own built-in retry, enabled by default for 5xx/429.
   It was compounding with this adapter's own retry — two independent retry loops multiplying
   delay instead of adding it, which hung a single transient 503 for over a minute. Fixed by
   disabling the SDK's internal retry (`attempts=1`) so `retry.py` is the only layer.
2. My first two guesses at a Gemini model id (`gemini-2.0-flash`, `gemini-2.5-flash`) are both
   fully retired for new API keys. Found the actual current id (`gemini-3.8-flash`) by listing
   the real account's available models rather than guessing a third time.

**Why there's still no successful live AI finding:** in the most recent live run, Gemini's free
endpoint returned 504/503/504 across all 3 attempts (each attempt genuinely slow — overloaded,
not a bug), then OpenRouter's one configured free model 404'd (the pre-existing
`require_parameters: true` issue), then Groq/Ollama correctly skipped as unconfigured. The
review ended `failed` with a safe, accurate error summary — no crash, no hang, no leaked key.
This proves the *failure path* works; it does not yet prove a *success* path, which Phase 5's
own "done when" line requires.

## What's left from you (please work through these)

1. **Decide how to get a successful live Gemini/provider run**, since that's the one remaining
   gap before Phase 5 task 1 can be called fully done:
   - Easiest: get a **Groq** API key (console.groq.com/keys) and a model id from
     console.groq.com/docs/models (team's stated preference: Llama 3.3 70B, Llama 4, or
     gpt-oss). Groq is a separate service from Gemini, so it sidesteps Gemini's current
     overload entirely. Put `GROQ_API_KEY` and `GROQ_MODEL` in `services/api/.env`.
   - Or: just try Gemini again later — `GEMINI_MODEL=gemini-3.8-flash` is confirmed valid and
     occasionally succeeds; the free endpoint may simply be past its demand spike by the time
     you retry.
   - Or: set up **Ollama** locally and set `OLLAMA_MODEL` in `.env`. This is the only provider
     usable for confidential sources (Phase 5 task 8), so you'll need it eventually regardless.

2. **Tell me which of these to pursue**, or if you'd rather I move on to Phase 5 tasks 5-8
   (cache, idempotency, rate limits, confidential routing) or Phase 7, with the mocked tests as
   sufficient proof for task 1 for now, and come back to a live success run later.

3. **Decide whether to flag the OpenRouter `require_parameters: true` issue to Member 2.** My
   adapter already works around it (falls through to the next provider regardless), so this is
   not blocking — but `OpenRouterProvider`'s *own* internal retry across multiple configured
   OpenRouter models still stops immediately on this error. Worth a heads-up to them, or not —
   your call, per "ask Member 2 via me before touching anything in services/verification."

4. **Review and confirm before I commit.** Everything through Phase 4 is already committed
   (your own commit `3dd3c59 "phase4"`). The Phase 5 provider adapter and all of Phase 6 are
   new, uncommitted work from this session.

5. **A reminder, not new**: every full `pytest` run (specifically `test_migrations.py`'s
   downgrade-to-`base`-then-upgrade cycle) wipes all data, including any demo org/user/brand
   seeded by hand. There's still no seed script (that's Phase 8) — reseed after running the
   full suite if you want persistent demo data between sessions, using the script in
   `services/api/API.md`.

## Known limitations (not bugs, just not done)

- No cache, no idempotency keys, no rate limiting yet — a resubmitted identical review re-runs
  the whole pipeline and makes new LLM calls every time.
- No confidential-source routing yet — a review with a `confidential` brand source currently
  still goes through whichever cloud provider answers first. **Do not rely on sensitivity
  marking for anything real until Phase 5 task 8 is built.**
- No seed script, no source-withdrawal/InkWatch flow (Phase 7), no deploy (Phase 8).
- The approval guard's "source superseded" check (Phase 6 task 4) looks at the *latest* version
  of each cited brand source and its current status — it does not yet distinguish a source that
  was superseded for an unrelated reason from one whose *cited section specifically* changed
  (that finer-grained diff is explicitly Phase 7's job, task 4).
- `GEMINI_MODEL` currently has no verified-working default in `.env.example` — the comment there
  correctly says "pick a current id," since even my first two concrete guesses were wrong.
