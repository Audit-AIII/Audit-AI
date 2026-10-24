# INKLOOM AI backend

Member 3's service: database, auth, tenant isolation, API, orchestration, versioning, approval
state machine, audit, failure handling, and the LLM provider adapter. See
[`../../member3_backend/00_CONTEXT.md`](../../member3_backend/00_CONTEXT.md) for the product
context and the shared contract this backend enforces, and
[`../../contract/README.md`](../../contract/README.md) for the status strings, role names and
example payloads shared with Members 1 and 2.

**Setting up locally and want the full route reference and the AI-engine setup walkthrough (API
keys and all)? See [`API.md`](API.md)** — this file is the project overview, current status,
architecture and commands; API.md goes deep on the HTTP contract.

**Status** (2026-10-24; see [`../../member3_backend/STATUS.md`](../../member3_backend/STATUS.md)):
individual-user mode - one email = one private account owning several brands; roles no longer gate
anything and the user approves their own content. Every route is live and verified against a real
Postgres database (288 tests, see "Test") and over real HTTP with a real AI provider
(`scripts/smoke_test.py`). New this round: real AI findings (verified model ids), finding categories,
suggested rewrites for contradicted claims, the review-queue list, Insights analytics and the Trust
Scorecard evaluation. Not deployed yet.

## Setup

```sh
cd services/api
python -m venv .venv
# Exact tested versions (constraints.txt), with Member 2's engine editable. Re-run after every pull:
# an older venv can keep stale, vulnerable packages (pip-audit found pypdf 5.9.0 in one on 2026-10-24).
.venv/Scripts/python -m pip install -e ".[dev]" -e ../verification -c constraints.txt   # macOS/Linux: .venv/bin/python

docker compose up -d                                       # local Postgres (needs Docker Desktop running)

cp .env.example .env    # fill in AUTH_SECRET_KEY; DATABASE_URL default matches docker-compose.yml
```

## Environment variables

Everything is documented inline in [`.env.example`](.env.example) — copy it to `.env` and fill
in what you need. Which AI keys each part needs, and the free-key findings:
[`AI_PROVIDER_KEYS.md`](AI_PROVIDER_KEYS.md). Summary:

| Variable | Required? | What it's for |
|---|---|---|
| `DATABASE_URL` | yes | Postgres connection string (psycopg3 driver) |
| `AUTH_SECRET_KEY` | yes | Signs session tokens — generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `GEMINI_API_KEY` / `GEMINI_MODEL`, `GROQ_API_KEY` / `GROQ_MODEL`, `OPENROUTER_API_KEY` / `INKLOOM_LLM_MODELS`, `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | no | The Phase 5 provider fallback chain, tried in that order. None configured → `POST /api/reviews` still works, writing one clearly-labelled stub finding instead of a real one |
| `RATE_LIMIT_SUBMISSIONS_PER_USER` / `_PER_ORGANISATION` / `_WINDOW_SECONDS` | no | Phase 5 task 7 rate limiting (defaults: 20/user, 100/org, per 60s) |

Never commit a filled-in `.env` — only `.env.example` is tracked (`.gitignore`). See
[`DISCLOSURE.md`](DISCLOSURE.md) for exactly what data leaves this process and when.

## Migrations

```sh
.venv/Scripts/python -m alembic upgrade head      # apply
.venv/Scripts/python -m alembic downgrade base    # drop everything (used by test_migrations.py)
```

## Seed demo data

```sh
.venv/Scripts/python scripts/seed.py
```

Creates two individual demo users, each with their own private account, two brands, approved
brand documents and demo content checked against them (see the script's docstring). Demo reviews
run through the offline scripted provider (`src/inkloom_api/engine/scripted_provider.py`, model
id `scripted/demo-v1`), so no API key is needed. Synthetic data only, clearly labelled
`[SEEDED]`. Idempotent per user (`--reset` deletes and reseeds both demo accounts). Prints each brand id.

**Reseed after running the full test suite.** `test_migrations.py`'s downgrade-to-`base`-then-
upgrade cycle wipes all data, seeded or not — this is deliberate (it proves migrations actually
reverse cleanly), not a bug, but it means demo data doesn't survive a full `pytest` run - run `scripts/seed.py --reset` after it.

## Test

```sh
.venv/Scripts/python -m pytest -q
```

Runs the whole suite against the real database at `DATABASE_URL` (DB-backed tests skip
automatically if it isn't reachable - CI fails on any skip). 288 tests, ~85s.
`.venv/Scripts/python -m alembic check` confirms the models match the migrations.
CI (`.github/workflows/repo-integrity.yml`, job 3) runs both on every push and pull request. Offline: every test that runs a review uses the
stub or the scripted provider (`src/inkloom_api/engine/scripted_provider.py`), never a real model.

## Smoke test

With the server running (see "Run" below) - no seed data needed:

```sh
.venv/Scripts/python scripts/smoke_test.py        # BASE_URL=http://host:port to point elsewhere
```

As a brand-new user, over real HTTP: register -> upload an approved document -> review a draft ->
list reviews -> fetch the review -> brand stats + analytics -> latest evaluation (404 before any
run) -> approve -> history. With a provider configured the review is real; without one the script
says it ran in stub mode.

## Run

```sh
.venv/Scripts/python -m uvicorn inkloom_api.main:app --reload
```

`GET http://localhost:8000/health` → `{"status": "ok"}`. Interactive docs at `/docs` and
`/redoc`. Analysis is **synchronous**: `POST /api/reviews` blocks until the review reaches a
final state (confirmed with the team) — no polling or background jobs in this phase.

## Architecture

| Path | Contents |
|---|---|
| `src/inkloom_api/main.py` | FastAPI app, middleware wiring, health check, loads `.env` into the real process environment (so the engine's own env-based config sees it too) |
| `src/inkloom_api/config.py` | Settings loaded from the environment / `.env` |
| `src/inkloom_api/logging.py` | Structured logging, request ID middleware |
| `src/inkloom_api/errors.py` | Safe error responses (stable code, safe message, request ID — never a stack trace or raw provider error) |
| `src/inkloom_api/db.py` | SQLAlchemy engine/session; one session per request |
| `src/inkloom_api/statuses.py` | Every status string and role name, single source of truth |
| `src/inkloom_api/models/` | SQLAlchemy ORM models, one file per domain area |
| `src/inkloom_api/schemas.py` | API response DTOs (never return a SQLAlchemy model directly) |
| `src/inkloom_api/auth/` | Password hashing/JWT (`security.py`), the role → permission table (`permissions.py`), the `get_current_membership`/`require_permission(...)` dependency every protected route uses (`dependencies.py`) |
| `src/inkloom_api/tenancy.py` | "Fetch by id, then check it resolves to this organisation" helpers — the thing that makes cross-tenant access structurally impossible rather than merely checked |
| `src/inkloom_api/routers/` | Route modules: `auth`, `brands` (brands, sources), `reviews` (submit, upload, list, get, rerun), `content` (new versions, history), `content_versions` (approve/request-changes), `analytics` (brand-risk), `evaluations` (Trust Scorecard) |
| `src/inkloom_api/review_queries.py` | Tenant-scoped review queries; the one definition of "waiting for the user's decision" |
| `src/inkloom_api/evaluation_runner.py` | Runs the engine's labelled evaluation through the provider chain, within the engine's call budget |
| `src/inkloom_api/softening_guard.py` | Backend rules check on any suggested wording for an unverified claim |
| `src/inkloom_api/engine/scripted_provider.py` | Offline, deterministic stand-in for a model (seed + tests only; model id `scripted/demo-v1`) |
| `src/inkloom_api/engine/provider.py` | `build_provider(confidential=...)`: picks the real fallback chain or signals "use the stub"; never even constructs a cloud provider when `confidential=True` |
| `src/inkloom_api/engine/providers/` | `gemini.py`/`groq.py`/`ollama.py` (one `LLMProvider` each), `retry.py` (shared bounded retry), `fallback.py` (`FallbackProvider`: tries each in order, falls through on any failure) |
| `src/inkloom_api/engine/pipeline.py` | Extraction → retrieval → verification → `Finding`/`EvidenceLink` rows; the stub fallback |
| `src/inkloom_api/review_runner.py` | Shared "build corpus, run pipeline" logic behind submit, new-version, and rerun — all three behave identically |
| `src/inkloom_api/approval_rules.py` / `approval_service.py` | The pure approval state machine, and its DB-aware guards (not-decidable, stale, superseded source) — see "Concurrency" below |
| `src/inkloom_api/source_lifecycle.py` / `section_diff.py` | Phase 7: manual withdraw, and automatic diff-based flipping of dependents when a source's *cited* section actually changes |
| `src/inkloom_api/result_cache.py` / `idempotency.py` / `rate_limit.py` | Phase 5 tasks 5-7, all documented as in-process/single-worker (see "Known limitations") |
| `src/inkloom_api/audit.py` | One place to write an `AuditEvent` |
| `migrations/` | Alembic migrations |
| `scripts/seed.py` / `scripts/smoke_test.py` | Phase 8 tasks 2-3 |
| `tests/` | Tests against a real Postgres, plus DB-free permission unit tests |

### Concurrency

Two decisions on the same review (e.g. an approve and a reject arriving close together) are
serialized at the database level: `_latest_review_or_404` (`routers/content_versions.py`) locks
the review row with `SELECT ... FOR UPDATE`, so the second transaction blocks until the first
commits, then correctly sees the new status and is rejected with a safe `409` instead of racing
it into a second, contradictory decision. See `tests/test_content_versioning.py`'s
`test_truly_concurrent_decisions_the_db_lock_serializes_them` — it uses real overlapping
transactions (via `threading.Event`s, not just sequential requests) to prove this, and fails
without the lock.

## Engine integration (Member 2)

Called in-process as a plain importable package (`inkloom_verify`), installed editable into
this service's venv — not as a separate HTTP service (confirmed with the team; never a second
database for the engine). `review_runner.py` builds the corpus from the brand's latest approved
sources and calls `engine/pipeline.py`, which calls the engine's extraction/retrieval/
verification pieces and writes `Finding`/`EvidenceLink` rows. The LLM calls themselves go
through this service's own provider adapter (`engine/providers/`), not a provider SDK the
engine calls directly — see `CONTRACTS.md` in `services/verification` for the open integration
questions this answers (tenant id from the authenticated context, not the request body; this
service generates `request_id` and owns validation-error handling).

### Why the backend runs its own claim pipeline (not `verify_request`)

The engine has a single entry point, `inkloom_verify.pipeline.verify_request` (request in, report
out). The backend deliberately does **not** call it: `engine/pipeline.py` drives the same engine
components claim by claim, because several things the backend must do happen *between* the
engine's steps or around a single claim, and `verify_request` only returns a finished report.
Option (b) of the 2026-10-24 plan, taken as the recommended default; reopen it if the team prefers routing through `verify_request`.

What the backend does that `verify_request` does not:
- **Its own evidence check** (`engine/evidence_validator.py`): every citation is re-validated
  against the backend's own copy of the approved source; a failure downgrades *that one claim*
  to unverified and is audited. (`verify_request` instead discards a whole report that fails its
  scope check.)
- **Safer wording, corrections and Intent-lock re-checked here** (`softening_guard.py`,
  `intent_lock_guard.py`) before anything is stored, whatever the engine returned.
- **Stub mode** (no provider configured), the **result cache**, **per-call logging** to
  `external_call_log`, **confidential routing** (Ollama only), and the backend's own **call
  budget** settings (`REVIEW_MAX_*`).
- **Brand rules** via `evaluate_rules` with the default accessibility checks
  (`engine/brand_rules.py`); `verify_request` runs `check_rules` only when rules are given.
- `completed` never means approved; a per-claim failure becomes one `engine_error` finding.

Shared with `verify_request` (the engine's own code, not a copy): extraction, BM25 retrieval,
the verifier and its **citation guard** (inside `verify_claim`), the corrector (re-check on), the
softener, the call budget wrapper, and since 2026-10-24 the **decision policy**:
`apply_policy(result, DecisionPolicy())` runs on every claim, so a SUPPORTED claim on less than
strong evidence, or a compound claim on one quote, still goes to a person
(`tests/test_decision_policy.py`).

Still different (known, accepted):
- `verify_request` reports sentences extraction could not turn into claims as request errors;
  the backend only keeps extraction's own errors.
- Retrieval: `verify_request` uses `BM25Retriever.for_request` and the config's `top_k`; the
  backend uses `BM25Retriever(documents)` with the engine's default `top_k`.
- The engine's `review_reasons` (why a SUPPORTED claim needs review) are not stored or returned
  yet; the finding only has `requires_human_review`.

## Frontend integration (Member 1)

Every route the frontend calls is live; full shapes and example JSON in `API.md`. A token is scoped
to the user's own account. `ReviewOut` carries `content_item_id`, `brand_id`, `brand_name`, `title`,
`version_number` and `text`, so no screen needs a second lookup. `span` offsets are Unicode **code
points**, not UTF-16 code units - a JS client highlighting that range must convert (e.g.
`Array.from(text).slice(start, end).join("")`).

## Known limitations

- The idempotency-replay cache and rate limiter (`idempotency.py`, `rate_limit.py`) are both
  in-process memory — correct for a single-process demo deployment, reset on restart, not
  shared across multiple worker processes. Documented in each module's own docstring.
- No seed script output survives a full `pytest` run — see "Seed demo data" above.
- The approval guard's "source superseded" check (Phase 6) looks at the *latest* version of
  each cited brand source and its current status — it does not distinguish a source superseded
  for an unrelated reason from one whose *cited section specifically* changed (that finer-
  grained diff is Phase 7's `section_diff.py`, which only decides whether a *dependent content
  version* flips to `source_changed`, not what the approval guard itself reports).
- Source conflict detection (Phase 7 task 7, marked optional in the phase doc) is not built.
- Free-tier model ids change; the ids in `.env.example` were verified against the providers' live
  lists and real calls on 2026-10-24. Re-check them there if calls start failing.
- No deploy yet.
