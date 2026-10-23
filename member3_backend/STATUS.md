# Member 3 (Backend) — Project Status

**Team:** CodeNinjas · **Product:** InkLoom AI · **Member:** Member 3 — Backend, Security & Governance
**Last updated:** 2026-10-23 · **Tag:** `v0.1.0-phase8` (commit `cf4a6bc`) — local, known-good build; not yet deployed
**Tests:** 99 / 99 passing against a real PostgreSQL database

> **2026-10-24: individual-user mode.** InkLoom is now one email = one private account, owning
> several brands. Roles no longer gate anything (`admin` = account owner), risk-based routing is
> off (`required_reviewer_role` is always null on new reviews), and the user approves their own
> content. Sections below that describe team roles and routing are historical; see
> `contract/README.md`, "Accounts and roles", for the current rules.

> Read this top to bottom to understand everything Member 3 built, why, and what's still open.
> `00_CONTEXT.md` in this folder is the governance contract this whole service enforces.

---

## 1. What Member 3 Owns

| Area | Description |
|---|---|
| Database | PostgreSQL schema, 16 tables, 8 Alembic migrations |
| Auth | Email + password login, JWT bearer tokens, role-based permissions |
| Tenant isolation | Every query scoped to the caller's organisation; cross-tenant access structurally impossible |
| API | FastAPI service, 15 HTTP routes across 5 routers |
| Orchestration | Calls Member 2's AI engine, builds the reference corpus, writes results |
| Versioning | Immutable content versions, one "current" version per item |
| Approval workflow | State machine: submit → review → approve/reject/request-changes |
| Audit | Append-only log of every tenant action |
| Failure handling | Safe, structured errors everywhere; never a raw stack trace or provider error |
| LLM provider adapter | Multi-provider fallback chain, retries, caching, rate limiting, confidential routing |

Nothing here edits Member 1's (frontend) or Member 2's (AI engine) code. Integration is one-directional: this service calls into Member 2's `inkloom_verify` package as a library, and exposes HTTP routes for Member 1 to call.

---

## 2. Infrastructure You (or a teammate) Need to Set Up

| # | What | Where | Status |
|---|---|---|---|
| 1 | PostgreSQL | Local via `docker-compose.yml` (`postgres:16-alpine`), or any managed Postgres in production | **Done locally.** Not deployed. |
| 2 | `.env` file | `services/api/.env`, copied from `.env.example` | **Done locally.** Never committed (gitignored). |
| 3 | `AUTH_SECRET_KEY` | Random secret for signing JWTs | **Done locally**, generated with `secrets.token_urlsafe(32)` |
| 4 | An LLM provider key | One of `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` | **Not working right now** — see §9 |
| 5 | Local Ollama (optional) | For confidential-content analysis with zero cloud exposure | Not set up |
| 6 | A hosting target | For the real deploy (Phase 8 task 6) | Not started — needs your decision |

**What you need to fetch:** a working, current model id for at least one of Gemini / Groq / OpenRouter (free tiers). This has been attempted three times across sessions and all three guesses were already retired or returned 404. The fix is to open each provider's live model-list page once and copy a current id — not guess again. See `.env.example` in `services/api/` for exactly which variables each provider needs.

---

## 3. Database

- **Engine:** PostgreSQL 16, run via Docker Compose (`services/api/docker-compose.yml`)
- **Driver:** `psycopg` (psycopg3), connection string in `DATABASE_URL`
- **Migrations:** Alembic, 8 migrations applied in order, `upgrade head` / `downgrade base` both verified to round-trip cleanly on a live database
- **ORM:** SQLAlchemy 2.0, models under `src/inkloom_api/models/`

### 3.1 Migration history

| # | File | What it added |
|---|---|---|
| 0001 | `initial_schema` | Every core table: organisations, users, memberships, brands, sources, content, reviews, findings, evidence, approval events, audit events, ops tables |
| 0002 | `brand_source_file_metadata` | File type + storage path on brand sources (Phase 4 uploads) |
| 0003 | `content_versioning` | `content_items.brand_profile_id`, `content_versions.is_current` + a partial unique index (one current version per item, enforced by the database itself) |
| 0004 | `evidence_links_set_null_on_delete` | Fixed a dangling-FK crash risk on evidence links |
| 0005 | `section_diff` | `source_versions.section_hashes`, `evidence_links.cited_section_hash` (Phase 7) |
| 0006 | `reviews_served_from_cache` | `reviews.served_from_cache` boolean (Phase 5) |
| 0007 | `ops_tables_review_id_set_null_on_delete` | Fixed the same dangling-FK risk on call-log/cache rows |
| 0008 | `risk_based_approval_routing` | Two new roles (`legal_reviewer`, `brand_manager`) + `reviews.required_reviewer_role` (Phase 9) |

### 3.2 Tables (16)

| Table | Purpose |
|---|---|
| `organisations` | One row per tenant |
| `users` | Login identity (email, bcrypt password hash) |
| `memberships` | Which user belongs to which organisation, with which role — this is where roles live, not on the user |
| `brand_profiles` | A brand within an organisation |
| `brand_sources` | A brand's reference document (e.g. a product fact sheet) — has a status (`draft`/`approved`/`superseded`/`archived`) and a sensitivity (`normal`/`confidential`) |
| `source_versions` | Immutable snapshot of a source's text, one per upload |
| `content_items` | A piece of content submitted for checking |
| `content_versions` | Immutable snapshot of that content's text, one per edit — exactly one `is_current=true` per item |
| `reviews` | One AI-analysis run against one content version |
| `findings` | One flagged (or cleared) claim from a review |
| `evidence_links` | The source quote backing (or contradicting) a finding |
| `approval_events` | A human decision: approved / rejected / changes_requested |
| `audit_events` | Append-only log of every tenant action, win or lose |
| `external_call_log` | Every real call made to an LLM provider — metadata only, never content |
| `idempotency_keys` | Dedupe table for retried writes |
| `result_cache` | Cached analysis reports, keyed per-tenant |

---

## 4. Directory Structure

```
services/api/
├── .env.example              # every environment variable, documented inline
├── docker-compose.yml        # local Postgres
├── alembic.ini
├── API.md                    # full HTTP route reference + setup walkthrough
├── README.md                 # project overview, architecture, commands
├── DISCLOSURE.md             # AI assistance + external services disclosure
├── migrations/versions/      # 8 Alembic migrations (see §3.1)
├── scripts/
│   ├── seed.py                # demo org, 7 role users, 2 approved sources, 4 demo reviews
│   └── smoke_test.py           # live end-to-end HTTP walkthrough
├── src/inkloom_api/
│   ├── main.py                # FastAPI app, middleware, /health
│   ├── config.py              # Settings (env-driven)
│   ├── db.py                  # SQLAlchemy engine/session
│   ├── logging.py             # structured logs, request-ID middleware
│   ├── errors.py              # safe error responses
│   ├── statuses.py            # every status string / role name — single source of truth
│   ├── tenancy.py             # "fetch by id, verify it's this org's" helpers
│   ├── audit.py                # one place to write an AuditEvent
│   ├── approval_rules.py      # pure approval state machine (no DB)
│   ├── approval_service.py    # DB-aware approval guards
│   ├── review_runner.py       # shared "build corpus, run pipeline" logic
│   ├── result_cache.py         # Phase 5 cache
│   ├── idempotency.py          # Phase 5 idempotency replay
│   ├── rate_limit.py           # Phase 5 rate limiting
│   ├── source_lifecycle.py     # Phase 7 withdraw / new-version diff
│   ├── section_diff.py         # Phase 7 section-hash diffing
│   ├── source_upload.py        # Phase 4 file upload handling
│   ├── models/                 # SQLAlchemy ORM models, one file per domain
│   ├── auth/
│   │   ├── security.py         # bcrypt hashing, JWT encode/decode
│   │   ├── permissions.py      # role → permission table
│   │   └── dependencies.py     # the auth dependency every route uses
│   ├── engine/
│   │   ├── pipeline.py          # extraction → retrieval → verification → findings
│   │   ├── provider.py          # assembles the provider fallback chain
│   │   ├── corpus.py            # builds the approved reference corpus
│   │   ├── evidence_validator.py # re-validates every citation independently
│   │   └── providers/
│   │       ├── gemini.py, groq.py, ollama.py   # one adapter class each
│   │       ├── retry.py          # shared bounded retry (429/5xx/timeout)
│   │       └── fallback.py       # tries each provider in order
│   ├── routers/
│   │   ├── auth.py, brands.py, reviews.py, content.py, content_versions.py
│   └── schemas.py              # API response shapes (never a raw ORM model)
└── tests/                       # 99 tests, real-Postgres + DB-free
```

---

## 5. Complete API Route Reference

All routes except `/health` and `/api/auth/login` require `Authorization: Bearer <token>`.

| Method & Path | Permission | Purpose |
|---|---|---|
| `GET /health` | none | Liveness check, confirms DB reachable |
| `POST /api/auth/login` | none | Email + password → JWT, scoped to one organisation |
| `GET /api/auth/me` | any active member | Current session info (user, org, role) |
| `GET /api/brands/{brand_id}/sources` | any active member | List a brand's reference sources |
| `POST /api/brands/{brand_id}/sources` | `manage_sources` | Upload a new source (.txt/.pdf/.docx) — starts as `draft` |
| `POST /api/brands/{brand_id}/sources/{source_id}/approve` | `manage_sources` | Approve a draft source for use in reviews |
| `POST /api/brands/{brand_id}/sources/{source_id}/withdraw` | `manage_sources` | Withdraw an approved source; flips dependent approvals |
| `POST /api/brands/{brand_id}/sources/{source_id}/versions` | `manage_sources` | Upload a new version of an existing source; diffs sections, flips only dependents whose cited section actually changed |
| `POST /api/reviews` | `submit` (+ rate-limited) | Submit content for AI review — **runs synchronously** |
| `GET /api/reviews/{review_id}` | any active member | Fetch a review's full result (findings + evidence) |
| `POST /api/reviews/{review_id}/rerun` | `submit` | Re-run analysis on the same content version |
| `POST /api/content/{content_item_id}/versions` | `submit` | Create a new content version (an edit) and auto-run a review on it |
| `GET /api/content/{content_item_id}/history` | any active member | Full version + decision history for one content item |
| `POST /api/content-versions/{content_version_id}/approve` | `approve` + risk-based routing | Approve a version — final sign-off |
| `POST /api/content-versions/{content_version_id}/request-changes` | `review` | Reject or request changes — always safe, never gated by routing/staleness |

### 5.1 Roles and permissions

| Role | submit | manage_sources | review | approve | administer |
|---|---|---|---|---|---|
| `submitter` | ✅ | | | | |
| `source_manager` | | ✅ | | | |
| `reviewer` | | | ✅ | | |
| `approver` | | | ✅ | ✅ | |
| `legal_reviewer` *(Phase 9)* | | | ✅ | ✅ | |
| `brand_manager` *(Phase 9)* | | | ✅ | ✅ | |
| `admin` | ✅ | ✅ | ✅ | ✅ | ✅ |

`admin` bypasses every guard in the system, including risk-based routing — it exists so one person can run a brand-new organisation alone.

---

## 6. The AI Workflow — Who Fetches What, From Where

This is the part most teammates ask about. Here is exactly what happens when content is submitted:

```
POST /api/reviews  (brand_id, text)
        │
        ▼
1. Build the corpus: fetch every APPROVED brand source's latest version (SQL query, no AI)
        │
        ▼
2. Check the result cache (hash of org + content + sources + engine version)
   → cache hit?  Materialize the stored findings. ZERO external calls. Done.
        │  (miss)
        ▼
3. Pick a provider chain:
   - Any source in scope marked CONFIDENTIAL?
       → chain = [Ollama only]. Gemini/Groq/OpenRouter are never even
         constructed — not skipped, structurally absent from the call.
   - Otherwise:
       → chain = [Gemini → Groq → OpenRouter(:free) → Ollama], tried in that
         fixed order. Any failure (429, timeout, 5xx, malformed output) falls
         through to the next provider in the chain.
        │
        ▼
4. None of the chain is configured (no API keys set anywhere)?
       → Write ONE static, clearly-labelled STUB finding
         (category: "stub", text starts "[STUB OUTPUT]").
         This is NOT real AI output — it exists only to prove the whole
         pipeline (auth → storage → response shape) works end to end
         without needing real credentials.
        │  (a provider IS configured)
        ▼
5. Real pipeline runs, using Member 2's engine (inkloom_verify), in-process:
   a. ClaimExtractor   — asks the LLM to pull factual claims out of the submitted text
   b. BM25Retriever    — keyword-search the approved source text for passages relevant
                          to each claim (no AI — pure retrieval, local)
   c. ClaimVerifier    — asks the LLM to judge each claim against the retrieved
                          passages: SUPPORTED / CONTRADICTED / NOT_ENOUGH_EVIDENCE
        │
        ▼
6. This backend independently re-checks every citation the LLM returned against
   its OWN copy of the source text (evidence_validator.py) — "the backend never
   trusts the engine." One bad citation downgrades that whole finding to unverified.
        │
        ▼
7. Write Finding + EvidenceLink rows. Log every real provider call (provider,
   model, latency, status — never content, never keys) to external_call_log.
        │
        ▼
8. Compute required_reviewer_role (Phase 9): any HIGH/CRITICAL finding → routes to
   legal_reviewer; otherwise → brand_manager.
        │
        ▼
9. Review status = completed (all claims supported) or needs_human_review
   (anything else). Cache the result (only if it was a genuine completed run).
```

**Which parts are "AI agents" vs static/deterministic:**

| Step | Real AI call? | Notes |
|---|---|---|
| Build corpus | No | Plain SQL |
| Cache check | No | Hash lookup |
| Claim extraction | **Yes** | One LLM call per submission |
| Passage retrieval (BM25) | No | Keyword search, runs locally, no network |
| Claim verification | **Yes** | One LLM call per extracted claim |
| Citation re-validation | No | String/offset matching against the backend's own copy of the source |
| Stub finding | No | Hard-coded placeholder text, used only when zero providers are configured |
| Risk-based routing | No | Deterministic rule on `Finding.severity`, no AI |

**Provider order and what each one is (free-tier target):**

| Order | Provider | Model family | Needs |
|---|---|---|---|
| 1 | Google Gemini | Gemini Flash | `GEMINI_API_KEY` + `GEMINI_MODEL` |
| 2 | Groq | Llama 3.3 70B / Llama 4 / gpt-oss | `GROQ_API_KEY` + `GROQ_MODEL` |
| 3 | OpenRouter | any `:free` model with structured-output support | `OPENROUTER_API_KEY` + `INKLOOM_LLM_MODELS` |
| 4 | Ollama | whatever's pulled locally | `OLLAMA_MODEL` (no key — runs on your machine) |

Every attempt (success or failure) is logged with a bounded retry (429 / 5xx / timeout only, never more) before falling through to the next provider. If **every** provider in the chain fails, the review becomes `failed` with a safe error summary — **never silently approved.**

---

## 7. Phase-by-Phase Summary

Keywords first, detail after. All phases 1–8 are done; Phase 9 has one of five stretch items done.

### Phase 1 — Foundation & Contract ✅
**Keywords:** project skeleton, SQLAlchemy models, Alembic, shared contract.
Set up the FastAPI project, the full initial database schema (every table), structured logging, safe error handling, and the `contract/` folder shared with Members 1 and 2 (status strings, role names, example payloads). Verified with a real `alembic upgrade head` / `downgrade base` round-trip.

### Phase 2 — Auth & Tenant Scoping ✅
**Keywords:** JWT, bcrypt, roles, tenant isolation.
Email + password login, bcrypt password hashing, JWT bearer tokens scoped to one organisation per token. Built the role → permission table and the `tenancy.py` helpers that make it structurally impossible to fetch another tenant's data — not just "checked," but unreachable by construction. Verified: login, token validation, revoked-membership rejection, cross-tenant access attempts.

### Phase 3 — Vertical Slice ✅
**Keywords:** submit → engine → findings → UI, synchronous.
Built the first real end-to-end path: `POST /api/reviews` → engine → `GET /api/reviews/{id}`. Confirmed with the team that analysis runs **synchronously** (the request blocks until done — no polling, no background jobs, by design for this project's scope). Added the stub-mode fallback so the whole pipeline is demoable without any API key.

### Phase 4 — Evidence Validation & Sources ✅
**Keywords:** file upload, draft/approved sources, independent citation re-check.
Real file uploads (.txt/.pdf/.docx) for brand reference sources, with a draft → approved workflow. Built `evidence_validator.py`: this backend independently re-checks every citation the AI engine returns against its own stored copy of the source text, rather than trusting the engine's own claim. Verified with real uploads through the live endpoint.

### Phase 5 — Provider Adapter, Cache, Idempotency, Rate Limits ✅
**Keywords:** fallback chain, confidential routing, cache, idempotency, rate limiting.
Built the full multi-provider adapter described in §6: Gemini → Groq → OpenRouter → Ollama fallback with bounded retries, result caching (per-tenant, never shared even for identical content), `Idempotency-Key` support so a retried submission never double-runs, per-user/per-org rate limiting, and confidential-source routing (cloud providers are never even constructed when a confidential source is in scope — proven by making the cloud builders raise if ever called).
Two real bugs found and fixed here: Gemini's SDK had its own conflicting retry loop; the first two guessed Gemini model ids were both already retired.

### Phase 6 — Versioning, Approval & Audit ✅
**Keywords:** state machine, stale-approval guard, audit trail.
Built the approval state machine: a review is decidable only from `completed`/`needs_human_review`. Added the content-versioning model (edit → new version, exactly one "current" version, enforced at the database level) and the full approve/reject/request-changes workflow with audit logging on every action. Found and fixed a real gap: content items never recorded which brand they belonged to, which blocked rerun/new-version from knowing which sources to check against.

### Phase 7 — Source Lifecycle (InkWatch) ✅
**Keywords:** manual withdraw, automatic section diff, dependent flipping.
When a brand source is withdrawn or replaced with a new version, every approval that depended on it must be re-examined. Built both the manual path (withdraw flips every dependent) and the automatic path (uploading a new source version diffs it section-by-section against the old one, and flips only the approvals whose *specific cited section* actually changed — not every approval touching that source). Source *conflict* detection (an optional task in this phase) was not built — not requested.

### Phase 8 — Tests, Seed, README, Deploy — mostly ✅
**Keywords:** test audit, seed script, smoke test, documentation, secret scan.
- **Task 1 (test checklist):** all 12 required governance tests pass, including closing two real gaps this session — a genuine concurrent-approval race condition (two simultaneous decisions could both succeed; fixed with a database row lock) and an explicit test that a permission denial writes no audit event while a real decision writes exactly one.
- **Task 2 (seed script):** `scripts/seed.py` — one demo organisation, one user per role, two approved brand sources, four demo content items (a terminology violation, a contradicted claim, an unsupported promise, a prompt-injection sample).
- **Task 3 (smoke test):** `scripts/smoke_test.py` — drives the full create → findings → request-changes → new-version → approve → audit path over real HTTP.
- **Task 4 (README):** rewritten to reflect current, real status (was describing Phase 3).
- **Task 5 (disclosure):** `DISCLOSURE.md` updated for every external service this backend calls.
- **Task 8 (secret scan):** full git history + current tree + the frontend + the engine scanned for leaked keys. Clean.
- **Not done:** Task 6 (deploy to a hosted target, tag a *public* release) and Task 7 (a recorded fallback demo video) — see §10.

### Phase 9 — Stretch (1 of 5 items) 🟡
**Keywords:** risk-based routing, legal_reviewer, brand_manager, deterministic.
**Item 1 done:** every review that finishes analysis is automatically routed to a `legal_reviewer` (if any finding is high/critical severity) or a `brand_manager` (everything else, including a clean review) — two new roles, enforced at the approval endpoint, not just a label. A human still always makes the actual decision; routing only decides *which* human may. Found and fixed a second real bug here too: the migration's rollback path didn't account for existing data using the new roles.
**Items 2–5 not started** — see §11.

---

## 8. Test Coverage & Verification

```sh
cd services/api
set -a; source .env; set +a
./.venv/Scripts/python.exe -m pytest -q
```

- **99 tests pass**, against a real PostgreSQL database (not mocked) — DB-backed tests skip automatically if no database is reachable.
- Covers: tenant isolation, revoked memberships, approval state machine, provider failure modes (429/timeout/malformed/all-down), idempotency, cross-org cache isolation, confidential-source routing, concurrent-decision locking, risk-based routing, migration round-trips.
- **One honest gap:** no test has captured a successful *real* AI finding end-to-end, because no free-tier provider has stayed reachable long enough during development (see §9). Every *failure* mode is fully proven, live and in mocked tests — only the success path through a real model hasn't been captured on camera.

---

## 9. What's Left — Action Items For You

| # | Action | Why it's blocked on you |
|---|---|---|
| 1 | **Get one working free-tier LLM model id.** | `.env`'s configured OpenRouter model currently 404s; nothing else is configured. This has failed 3 times across sessions on guessed model ids. Visit the provider's own live model list (Gemini: ai.google.dev/gemini-api/docs/models · Groq: console.groq.com/docs/models · OpenRouter: openrouter.ai/models) and copy a current id — don't guess again. |
| 2 | **Decide on a deploy target** (Phase 8 task 6). | Touches real external infrastructure and costs — needs your call on which free host, and confirmation before anything is stood up. |
| 3 | **Record a fallback demo video** (Phase 8 task 7). | A judgment call on what to show, needs you on camera/screen. |
| 4 | **Review and commit this session's uncommitted work.** | Phase 9 item 1 (two new roles, migration 0008, 15 tests) is new since the last commit — review the diff before it's committed. |
| 5 | **Decide what Phase 9 item to do next** (items 2–5, see §11) — or stop here. | Your call on priority; the phase doc says "cut from the bottom first" if time runs short. |

---

## 10. Tasks That Depend On Your Teammates

| # | What | Needs input from | Status |
|---|---|---|---|
| 1 | Confirm Member 1's frontend can resolve `content_item_id` when creating a new version. | Member 1 | `ReviewOut` currently never exposes `content_item_id` — the test suite and the smoke test both work around this with a direct database lookup. Flag this to Member 1; their Correction Editor screen may hit the same wall. |
| 2 | OpenRouter `require_parameters: true` retry behavior. | Member 2 | Not blocking (this backend's own fallback chain already works around it by moving to the next provider), but Member 2's `OpenRouterProvider` stops its *own* internal retry immediately on this error — worth a heads-up. |
| 3 | Phase 9 item 4 — "change-impact events" (a new content version that strengthens a guarantee, alters a number, or removes a disclaimer should raise a flag). | Member 2 | Explicitly listed in the phase doc as needing coordination with the engine team — not started. |
| 4 | Real frontend + real engine smoke test together. | Member 1 + Member 2 | `scripts/smoke_test.py` proves the backend alone; the phase 8 doc also asks for one run with all three pieces live together — not yet done as a joint session. |

---

## 11. Optional / Not Done

| Phase | Task | Status | Reason |
|---|---|---|---|
| 7 | Task 7 — source conflict detection | **Not started.** Explicitly marked *optional* in the phase doc. | Not requested by the team. |
| 8 | Task 6 — deploy to a hosted target, tag a public release | Not started | Needs your decision (§9) |
| 8 | Task 7 — fallback demo path / recorded backup video | Not started | Needs you (§9) |
| 9 | Item 2 — real analytics (`GET /api/analytics/brand-risk`) | Not started | Next in priority order per the phase doc |
| 9 | Item 3 — hash-linked audit verification ("tamper-evident" chain) | Not started | — |
| 9 | Item 4 — change-impact events on a new version | Not started | Needs Member 2 (§10) |
| 9 | Item 5 — audit pack export (PDF per item) | Not started | Lowest priority — "cut from the bottom first" |

---

## 12. Known Limitations (Not Bugs, Just Not Done)

- **Idempotency cache and rate limiter are in-process memory** — correct for a single-process demo, but reset on restart and not shared across multiple worker processes. Documented in each module's own file, not hidden.
- **No organisation switcher, no polling, no background jobs** — all explicit, confirmed simplifications for this project's scope, not oversights.
- **`ReviewOut` never exposes `content_item_id`** — see §10.
- **A plain `approver` can no longer approve a *routed* review** post-Phase-9 — a deliberate consequence of real role-based routing, not an accident. Use `legal_reviewer`/`brand_manager`/`admin` for anything new.
- **Every full `pytest` run wipes all data**, including seeded demo data (`test_migrations.py`'s downgrade-to-base-then-upgrade cycle proves migrations reverse cleanly, which requires actually dropping everything). Reseed with `scripts/seed.py` after running the full suite.
- **The approval guard's "source superseded" check** looks at a cited source's *latest* version and current status — it doesn't yet distinguish "superseded for an unrelated reason" from "the *cited section specifically* changed" (that finer distinction is Phase 7's section-diff feature, which only governs automatic approval-flipping, not this guard).

---

## 13. Quick Reference

```sh
# Setup
cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pip install -e ../verification
docker compose up -d
cp .env.example .env   # fill in AUTH_SECRET_KEY

# Migrate
.venv/Scripts/python -m alembic upgrade head

# Seed demo data
.venv/Scripts/python scripts/seed.py

# Run
.venv/Scripts/python -m uvicorn inkloom_api.main:app --reload

# Smoke test (server must be running; use the BRAND_ID seed.py prints)
BRAND_ID=<id> .venv/Scripts/python scripts/smoke_test.py

# Full test suite
set -a; source .env; set +a; .venv/Scripts/python -m pytest -q
```

See `services/api/README.md` for the architecture deep-dive and `services/api/API.md` for full request/response payload examples.
