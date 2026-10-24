# INKLOOM AI backend

Member 3's service: database, auth, tenant isolation, API, orchestration, versioning, approval
state machine, audit, failure handling, and the LLM provider adapter. See
[`../../docs/backend.md`](../../docs/backend.md) for the product
context, design decisions and the shared contract this backend enforces, and
[`../../contract/README.md`](../../contract/README.md) for the status strings, role names and
example payloads shared with Members 1 and 2.

**Setting up locally and want the full route reference and the AI-engine setup walkthrough (API
keys and all)? See [`API.md`](API.md)** — this file is the project overview, current status,
architecture and commands; API.md goes deep on the HTTP contract.

**Status** (2026-10-24; see [`../../docs/backend.md`](../../docs/backend.md)):
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

**Never run the suite against a database you care about:** `test_migrations.py` downgrades to
`base`, which drops every table (it once wiped the dev seed data). Use a throwaway schema in the
same database instead; it needs no extra privileges:

```sh
set -a; source .env; set +a                                      # DATABASE_URL = your dev database
python -c "import os; from sqlalchemy import create_engine, text; e = create_engine(os.environ['DATABASE_URL']); c = e.connect(); c.execute(text('CREATE SCHEMA IF NOT EXISTS inkloom_test')); c.commit()"
export DATABASE_URL="${DATABASE_URL}?options=-csearch_path%3Dinkloom_test"   # tests only see this schema
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m pytest -q
```

DB-backed tests skip automatically if the database isn't reachable (CI fails on any skip).
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

## Deploy

**Not deployed yet**: the host and budget are not chosen. Everything a container host needs is
in the repo and was rehearsed locally on 2026-10-24 (the production start below migrated, served
`/health` 200, and refused to start with `CORS_ALLOW_ORIGINS=*`). The Docker image itself has
not been built yet (Docker was not running on the dev machine).

**What runs**
- Image: `services/api/Dockerfile`, built from the **repository root** (it needs the engine too):
  `docker build -f services/api/Dockerfile -t inkloom-api .`. The root `.dockerignore` keeps
  every `.env`, venv and local upload out of the image.
- Start: `scripts/start.sh` runs `alembic upgrade head`, then uvicorn with **exactly one worker**
  (the review rate limiter is in memory). For a host without Docker, use the same start command
  from `services/api` after `pip install -e . -e ../verification -c constraints.txt`.
- Health check: `GET /health` (the image also has a Docker `HEALTHCHECK`).
- Database: a managed PostgreSQL 16+ instance.

**Environment (set in the host's settings; never in the repo or the image)**

| Variable | Value |
|---|---|
| `DATABASE_URL` | the managed Postgres URL, as `postgresql+psycopg://...` |
| `AUTH_SECRET_KEY` | 32+ random characters (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) |
| `ENVIRONMENT` | `production` (the image sets it): refuses to start on a missing/short key or `*` CORS |
| `CORS_ALLOW_ORIGINS` | the exact public frontend URL, e.g. `https://inkloom.example.com`; never `*` |
| `PORT` | set by most hosts; defaults to 8000 |
| AI provider keys | see [`AI_PROVIDER_KEYS.md`](AI_PROVIDER_KEYS.md). Keep `INKLOOM_LLM_DATA_COLLECTION=deny`; set `GEMINI_PAID_TIER=true` only for a paid key. Without any key, reviews return the labelled stub. |

**Things to know on a cloud host**
- **Confidential documents fail closed.** A review whose brand has a `confidential` document only
  ever uses local Ollama, which a cloud host doesn't have: no cloud provider is tried, the review
  gets the labelled stub finding, and nothing leaves the server
  (`tests/test_phase5_cache_idempotency_confidential.py`).
- Uploaded files are kept on the container's disk (`var/brand_sources`), which most hosts wipe on
  redeploy. Only the raw file is lost: the extracted text every review uses is in the database.
- Behind the host's proxy every client may share one IP, so the registration rate limit
  (`RATE_LIMIT_REGISTRATIONS_PER_IP`) applies to all sign-ups together. It never trusts
  `X-Forwarded-For`.

**After the first deploy**
1. `python scripts/seed.py` once on the deployed database (never `--reset` on anything real; it
   only adds the two `[SEEDED]` demo accounts and skips them if they exist).
2. `BASE_URL=https://<public-api-url> python scripts/smoke_test.py`: register, upload a
   document, review, list, fetch, analytics, decision and history over real HTTP.
3. Check CI on `main` is green, then tag the release (`git tag known-good-<date>`).

## Demo rehearsal

Seed first (`scripts/seed.py`; works with no AI key). Every seeded name and title says
`[SEEDED]` and every seeded model id is `scripted/demo-v1`, so nothing seeded is presented as
real AI output.

1. **Sign in** as `asha@seed.inkloom.demo`, password `SeedDemo!2026-not-a-real-secret`
   (`POST /api/auth/login`).
2. **Dashboard** (`GET /api/brands`): two brands, *Lumen Audio [SEEDED]* and *Kora Phones
   [SEEDED]*, each with approved documents, review counts and open reviews.
3. **Review queue** (`GET /api/reviews`): seven drafts covering every state: completed, needs
   review, approved, changes requested, and one *source changed*.
4. **Open "[SEEDED] Lumen Pods launch post"** (`GET /api/reviews/{id}`): "up to 24 hours of
   playback" is contradicted, with the quote from the approved fact sheet and an evidence-backed
   suggested rewrite to 12 hours.
5. **Open "[SEEDED] Kora X2 launch ad":** "India's number one smartphone" is unverified (no
   document mentions rankings: unverified, never "false"). "[SEEDED] Lumen Pods summer ad" shows
   both kinds: "waterproof for any swim" contradicted, "best-selling earbuds in Europe" unverified.
6. **Versions:** "[SEEDED] Kora X2 spec sheet copy": v1 ("6,000 mAh", contradicted) was sent back
   with changes requested; v2 was approved.
7. **Source Watch:** "[SEEDED] Lumen Pods colour announcement" was approved, then the colour-range
   document it cited was superseded, so it is *source changed* and back for review
   (`GET /api/content/{id}/history` shows the decisions).
8. **Insights** (`GET /api/analytics/brand-risk?brand_id=...`): real turnaround and queue ages from
   the seeded timestamps.
9. **Live, without an AI key** (deterministic checks): add a brand rule
   (`PUT /api/brands/{id}/rules` with a prohibited term, e.g. "guaranteed" -> "designed"), then
   paste "Guaranteed comfort. BUY NOW TODAY." as a new draft: a terminology finding with its
   suggestion and an accessibility (all-caps) finding appear. The claim check shows the labelled
   stub until a provider key is set.
10. **Live, with an AI key:** paste a draft with a wrong figure, open the contradicted claim and its
   evidence, lock a must-keep phrase (`PUT /api/content-versions/{id}/locks`), re-check, and show
   that no suggestion removes it.
11. **Decide:** mark a draft ready to publish (`POST /api/content-versions/{id}/approve`) and show
    the history.

Left for people: record the fallback demo video (in case the live provider is down); see
[`docs/backend.md`](../../docs/backend.md), "Pending actions".

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

- The rate limiter (`rate_limit.py`) is in-process memory: correct for the single-worker
  deployment above, reset on restart. Idempotency keys are in the database.
- No seed script output survives a full `pytest` run — see "Seed demo data" above.
- The approval guard's "source superseded" check (Phase 6) looks at the *latest* version of
  each cited brand source and its current status — it does not distinguish a source superseded
  for an unrelated reason from one whose *cited section specifically* changed (that finer-
  grained diff is Phase 7's `section_diff.py`, which only decides whether a *dependent content
  version* flips to `source_changed`, not what the approval guard itself reports).
- Source conflict detection (Phase 7 task 7, marked optional in the phase doc) is not built.
- Free-tier model ids change; the ids in `.env.example` were verified against the providers' live
  lists and real calls on 2026-10-24. Re-check them there if calls start failing.
- Not deployed yet (host not chosen); see "Deploy".
