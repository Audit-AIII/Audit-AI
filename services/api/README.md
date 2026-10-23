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

**Status** (see [`../../member3_backend/STATUS.md`](../../member3_backend/STATUS.md) for the
full phase-by-phase detail): Phases 1-7 are built and verified against a real Postgres database,
including live end-to-end runs through real HTTP calls. Phase 8 task 1 (the required test
checklist) is fully done — 84 tests pass in one command (see "Test" below). The rest of Phase 8
(this README, the seed script, the smoke test script, deploy) is in progress; deploy has not
happened yet.

## Setup

```sh
cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"          # on macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pip install -e ../verification    # Member 2's engine, editable

docker compose up -d                                       # local Postgres (needs Docker Desktop running)

cp .env.example .env    # fill in AUTH_SECRET_KEY; DATABASE_URL default matches docker-compose.yml
```

## Environment variables

Everything is documented inline in [`.env.example`](.env.example) — copy it to `.env` and fill
in what you need. Summary:

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
`[SEEDED]`. Idempotent per user. Prints each brand id.

**Reseed after running the full test suite.** `test_migrations.py`'s downgrade-to-`base`-then-
upgrade cycle wipes all data, seeded or not — this is deliberate (it proves migrations actually
reverse cleanly), not a bug, but it means demo data doesn't survive a full `pytest` run.

## Test

```sh
.venv/Scripts/python -m pytest -q
```

Runs the whole suite against the real database at `DATABASE_URL` (DB-backed tests skip
automatically if it isn't reachable). 84 tests, ~25s.

## Smoke test

With the server running (see "Run" below) and `scripts/seed.py` already run for its `BRAND_ID`:

```sh
BRAND_ID=<id from seed.py> .venv/Scripts/python scripts/smoke_test.py
```

Drives the full demo path over real HTTP: create review → fetch findings → request changes →
create new version → approve → inspect audit history. See the script's own docstring for one
real pre-existing contract gap it had to work around (`ReviewOut` never exposes
`content_item_id`).

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
| `src/inkloom_api/routers/` | Route modules: `auth`, `brands` (sources), `reviews`, `content` (new versions, history), `content_versions` (approve/request-changes) |
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

## Frontend integration (Member 1)

Every route in `00_CONTEXT.md`'s route map is live. Auth: `POST /api/auth/login`,
`GET /api/auth/me`. A token is scoped to one organisation, decided at login (a user in more
than one organisation gets whichever membership was created first — no org switcher). `span`
offsets in findings are Unicode **code points**, not UTF-16 code units — a JS client
highlighting that range must convert (e.g. `Array.from(text).slice(start, end).join("")`)
whenever the text may contain characters outside the Basic Multilingual Plane. Full request/
response shapes and the error-code table are in `API.md`.

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
- `GEMINI_MODEL` has no verified-working default in `.env.example` — free-tier model ids change
  often enough that even two concrete guesses during this build were already retired; pick a
  current one from the provider's own model list.
- `ReviewOut` never exposes `content_item_id`, only `content_version_id` — creating a new
  version of existing content currently requires knowing the content item id by some other
  means (the test suite and `scripts/smoke_test.py` both fetch it via a direct DB query,
  documented at the call site). This is a real, pre-existing contract gap, not a new one — worth
  raising with the team if Member 1 hits the same wall.
- No deploy yet.
