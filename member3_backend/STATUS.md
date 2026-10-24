# Member 3 (Backend) — Project Status

**Team:** CodeNinjas · **Product:** InkLoom AI · **Member:** Member 3 — Backend, Security & Governance
**Last updated:** 2026-10-24 · **Tests:** 214 / 214 passing against a real PostgreSQL database ·
**Smoke test:** passing over real HTTP with a real AI provider · not yet deployed

> `00_CONTEXT.md` in this folder is the original governance contract. Where it mentions team roles,
> reviewer tiers or routing, the **individual-user product decision** below overrides it.

---

## 0. Product decision (2026-10-24): individual-user mode

InkLoom is an **individual-user app**: one email = one private account, owning several brands. A
user sees only their own brands, sources, content and reviews. They check drafts against their
brand's approved documents; claims without evidence are **unverified** (never "false") and get a
suggested safer rewrite where one can be offered; they approve their own content.

Implemented without changing the UI or dropping anything:

- Each `organisation` is one user's private account (register creates it). Tables, columns, enums,
  routes and field names are unchanged.
- **Roles no longer gate anything.** Every active membership holds every permission
  (`auth/permissions.py`). Register still writes `role = "admin"`, which now means **account owner**.
- **Risk-based routing is off.** New reviews get `required_reviewer_role = null` (UI: "Any approver").
  Column and migration 0008 are kept. The routing approval guard was removed.
- Approval guards that remain: review finished, version current, cited source not replaced.
  (Older docs said "admin bypasses every guard" — that was never true; admin only skipped routing,
  and routing is now off for everyone.)
- Cross-account isolation is the security boundary: any other account's id is a `404` identical to a
  random id (code and message). Tests: `test_cross_account_isolation.py`, `test_tenant_scoping.py`.

---

## 1. What Member 3 owns

| Area | Description |
|---|---|
| Database | PostgreSQL, 17 tables, 9 Alembic migrations |
| Auth | Email + password, JWT bearer tokens, self-serve registration (one private account per email) |
| Isolation | Every query scoped to the caller's own account; other accounts' data unreachable by construction |
| API | FastAPI, 23 HTTP routes across 7 routers |
| Orchestration | Calls Member 2's engine in-process (extraction, retrieval, verification, **correction**), writes results |
| Versioning | Immutable content versions, exactly one current version per item |
| Approval | The owner approves / requests changes; stale and source-drift guards |
| Audit | Append-only log of every state change |
| Failure handling | Safe structured errors; a provider failure never becomes an approval |
| Provider adapter | Gemini → Groq → OpenRouter → Ollama fallback, retries, cache, rate limits, confidential routing |
| Analytics / Scorecard | Insights numbers from real rows; Trust Scorecard runs the engine's labelled evaluation |

Nothing here edits Member 1's (frontend) or Member 2's (engine) code.

---

## 2. Infrastructure

| # | What | Status |
|---|---|---|
| 1 | PostgreSQL (`docker-compose.yml`, local port per `.env`) | Done locally. Not deployed. |
| 2 | `services/api/.env` from `.env.example` | Done locally, gitignored. |
| 3 | `AUTH_SECRET_KEY` | Done locally. |
| 4 | An LLM provider | **Working.** Gemini `gemini-3.5-flash-lite` (primary) + OpenRouter `nvidia/nemotron-3.5-super-vl:free` (fallback), ids read from the providers' live lists and confirmed with real calls on 2026-10-24. |
| 5 | Local Ollama (confidential sources) | Not set up |
| 6 | Hosting target | Not started — needs your decision |

Model-id history: three earlier guesses failed (retired or 404). The fix was reading the live lists:
`gemini-3.8-flash` (listed stable) times out from a free-tier key; `gemini-2.5-*` now 404 for new
users; the previous OpenRouter id lacked `response_format` and 404'd under `require_parameters`.

---

## 3. Database

PostgreSQL 16, psycopg3, SQLAlchemy 2.0, Alembic. `upgrade head` / `downgrade base` round-trip
verified on a live database (and by `tests/test_migrations.py` on every run).

| # | Migration | What it added |
|---|---|---|
| 0001 | `initial_schema` | All core tables |
| 0002 | `brand_source_file_metadata` | File type + storage path on brand sources |
| 0003 | `content_versioning` | `content_items.brand_profile_id`, one-current-version partial unique index |
| 0004 | `evidence_links_set_null_on_delete` | Dangling-FK fix |
| 0005 | `section_diff` | Section hashes for InkWatch |
| 0006 | `reviews_served_from_cache` | Cache flag |
| 0007 | `ops_tables_review_id_set_null_on_delete` | Dangling-FK fix |
| 0008 | `risk_based_approval_routing` | Two roles + `reviews.required_reviewer_role` (kept; routing now off) |
| 0009 | `evaluation_runs` | **New.** Trust Scorecard runs |

Tables: `organisations` (= accounts), `users`, `memberships`, `brand_profiles`, `brand_sources`,
`source_versions`, `content_items`, `content_versions`, `reviews`, `findings`, `evidence_links`,
`approval_events`, `audit_events`, `external_call_log`, `idempotency_keys`, `result_cache`,
`evaluation_runs`.

---

## 4. Routes (all live)

All except `/health`, login and register need `Authorization: Bearer <token>`. Full shapes and
example JSON: `services/api/API.md`.

| Method & path | Purpose |
|---|---|
| `GET /health` | Liveness + DB |
| `POST /api/auth/register` · `POST /api/auth/login` · `GET /api/auth/me` | Account + session |
| `GET /api/brands` · `POST /api/brands` | Brand list (with `review_count`, `open_review_count`, `last_review_at`) / create |
| `GET /api/brands/{id}/sources` · `POST .../sources` | List / upload documents (`approve=true` to approve on upload) |
| `POST .../sources/{sid}/approve` · `.../withdraw` · `.../versions` | Document lifecycle (InkWatch) |
| `POST /api/reviews` · `POST /api/reviews/upload` | Check pasted text / an uploaded draft |
| `GET /api/reviews` | **New.** Review queue: plain array of full reviews, `status` (repeatable), `brand_id`, `limit`, `offset` |
| `GET /api/reviews/{id}` · `POST /api/reviews/{id}/rerun` | One review / re-check |
| `POST /api/content/{id}/versions` · `GET /api/content/{id}/history` | Edit → new version + review / history |
| `POST /api/content-versions/{id}/approve` · `.../request-changes` | Owner's decision |
| `GET /api/analytics/brand-risk` | **New.** Insights |
| `GET /api/evaluations/latest` · `POST /api/evaluations` | **New.** Trust Scorecard |

---

## 5. The review workflow

```
POST /api/reviews (brand_id, text)
 1. corpus = the brand's APPROVED documents, latest version each (SQL)
 2. result cache (per account) - hit: replay, zero provider calls
 3. provider chain: confidential source in scope -> Ollama only; else Gemini -> Groq -> OpenRouter -> Ollama
 4. none configured -> one labelled stub finding (category "stub", "[STUB OUTPUT] ...")
 5. engine (in-process):
      ClaimExtractor -> BM25 retrieval -> ClaimVerifier
      CONTRADICTED -> ClaimCorrector (engine's own, recheck on): evidence-backed rewrite
      NOT_ENOUGH_EVIDENCE -> engine softening step, once Member 2 ships it (handoff)
 6. backend re-validates every citation against its own copy of the source; a bad one downgrades
    the finding to unverified and drops its suggestion
 7. findings get a category (contradicted_claim / unsupported_claim / supported_claim / engine_error);
    suggested_correction stored as the whole rewritten claim span
 8. every provider call (incl. correction + re-check) logged to external_call_log, metadata only
 9. status = completed (all supported) or needs_human_review; required_reviewer_role = null
```

Real-model check (2026-10-24, gemini-3.5-flash-lite): "up to 24 hours of playback" → contradicted,
quote "up to 12 hours of playback per charge", suggestion "Lumen Pods offer up to 12 hours of
playback per charge."; "India's number one …" → unverified; "2-year warranty" → supported.

---

## 6. History

**Phases 1–8 (done):** foundation and contract; auth and tenant scoping; synchronous vertical
slice with stub mode; file uploads and independent citation re-validation; provider fallback chain,
cache, idempotency, rate limits, confidential routing; versioning, approval state machine and
audit (incl. a DB row lock against concurrent decisions); InkWatch source withdraw / section-diff
flipping; tests, seed, smoke test, README, secret scan. **Phase 9:** risk-based routing was built,
then switched off by the individual-user decision.

**Individual-user round (2026-10-24), one commit per step on main:**

| Step | Commit | What |
|---|---|---|
| 1 | `d0a55f3` | Verified model ids; first real (non-stub) review |
| 2 | `a85e447` | Individual-user mode, routing off, seed rewritten, cross-account tests (found + fixed a 404-message leak on other accounts' reviews) |
| 3 | `a33f56c` | `Finding.category`, `brand_name`, evidence `source_title`/`source_version_number`, brand review stats |
| 4a | `86b4f91` | Suggested rewrites for contradicted claims (engine corrector, recheck on) |
| 4b | `47399d7` | Unverified-claim suggestions: backend side + `HANDOFF_unverified_suggestions.md` for Member 2 |
| 5 | `05e0447` | `GET /api/reviews` |
| 6 | `8c2fb67` | `GET /api/analytics/brand-risk` |
| 7 | `2628379` | Trust Scorecard + migration 0009 |
| 8 | `3e3a897` | Demo seed covering every state |
| 9 | `8c05137` | Docs, contract schemas, smoke test |
| fix | tag `known-good-2026-10-24` | Resolved the merge conflicts committed in `68b9b59` (main, evaluations router + tests, API.md): kept the POST / 404 Scorecard design. The engine dataset grew to 80 claims in `6b23c11`; tests now read its size instead of hardcoding 55 |
| fix | branch `fix/main-green` | Re-verified main after direct pushes broke it (`IndentationError` in `test_evaluations.py`). Krish's `member2/fix-plan-2-5-6-8` (incl. `f9f18a8` re-indent and `cc145f7` backend changes) was already on main via PR #1; no conflict markers; full suite 212 passed / 0 skipped against PostgreSQL; server boots (`/health` 200). No code changes needed |

Trust Scorecard real run (gemini-3.5-flash-lite, engine dataset of 55 claims at the time; it is now 80): 53 answered,
catch_rate 1.0 (35/35), false_positive_rate 0.0 (0/18 answered supported). Small synthetic set —
`limits_note` says it shows testing, not universal accuracy. A run with `gemini-3.6-flash` ran out
of time on free-tier 503s; such runs (>20% claims without a verdict) are now refused and not stored.

---

## 7. Tests

```sh
cd services/api
set -a; source .env; set +a
.venv/Scripts/python -m pytest -q          # 214 passed, 0 skipped, ~66s, real PostgreSQL 18.6 (2026-10-24, after merging fix/main-green and chore/single-user-decision onto 3b319e6)
```

Covers: cross-account isolation (every route), revoked memberships, approval guards and state
machine, concurrent decisions, provider failure modes, idempotency, cache isolation, confidential
routing, finding categories, suggested corrections (accepted / rejected / re-check / provider
failure / validation downgrade), unverified-suggestion guard, review queue, analytics (exact values
with pinned timestamps), evaluations (404 / 409 / budget / discard / rate limit), seed, contract-schema
drift, migration round-trip. Every test that runs a review is offline (stub or scripted provider).
The real-model success path is shown by `scripts/smoke_test.py` and the runs in §5–6.

A full run wipes the database (migration round-trip) — reseed with `scripts/seed.py --reset`.

---

## 8. What's left — for you

| # | Action |
|---|---|
| 1 | Decide a deploy target (needs your call on host and costs). |
| 2 | Record the fallback demo video. |
| 3 | Tell Member 1 the differences listed in §9. |
| 4 | Send `HANDOFF_unverified_suggestions.md` to Member 2. |

## 9. Notes for teammates

**Member 1 (frontend):**
- `suggested_correction` is the whole rewritten `original_text` (fits `draft.replace`).
- `open_review_count` / queue age count only the latest review of each item's current version.
- `brand-risk` accepts no `brand_id` (whole account); the page always sends one, so no change needed.
- `POST /api/evaluations` can answer 409 for "no provider" and for "too many provider failures, not
  saved", and 429 within 10 minutes — all with readable messages (the UI shows 409 text as-is). It
  takes ~1–4 minutes (synchronous).
- `ReviewOut.content_item_id` is present on every review (the old gap is closed).

**Member 2 (engine):** `HANDOFF_unverified_suggestions.md` — a softening step for
NOT_ENOUGH_EVIDENCE claims (`ClaimSoftener`, prompt `soften-claim-v1`). The backend calls it as
soon as `inkloom_verify.softening` exists. Also still open from earlier: OpenRouter's internal retry
stops on the `require_parameters` 404 (the backend's own fallback works around it).

## 10. Known limitations

- Rate limiter and idempotency replay are in-process memory (single worker). The evaluation's
  10-minute limit is in the database.
- No invites, org switcher, password reset or email verification (by design for individual accounts).
- Unverified claims get no suggested wording until the engine's softening step ships.
- Source conflict detection (Phase 7 optional) and Phase 9 items 3–5 not built.
- Not deployed.
