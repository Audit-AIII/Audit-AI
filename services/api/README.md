# INKLOOM AI backend

Member 3's service: database, auth, tenant isolation, API, orchestration, versioning, approval
state machine, audit, failure handling, and the LLM provider adapter. See
[`../../member3_backend/00_CONTEXT.md`](../../member3_backend/00_CONTEXT.md) for the product
context and the shared contract this backend enforces, and
[`../../contract/README.md`](../../contract/README.md) for the status strings, role names and
example payloads shared with Members 1 and 2.

**Setting up locally and want to know exactly what's needed for the AI engine to actually run
(API keys and all)? Start with [`API.md`](API.md)** — it has the full setup walkthrough and the
complete route reference; this file is the project overview.

**Status:** Phases 1-3 are built: project skeleton and migrations, auth and tenant scoping
(email+password login, JWT, the permission table, tenant-scoped lookups), and the vertical
slice — `POST /api/reviews` and `GET /api/reviews/{id}`, running analysis **synchronously**
(confirmed with the team: the request blocks until the engine finishes; no polling yet).
**Still not verified against a live database** — see "Verification status" below; nothing past
offline/unit checks has been run yet because Docker has not been reachable in this environment.

The engine (Member 2, [`services/verification`](../verification)) is called in-process, as a
plain importable Python package (`inkloom_verify`) installed editable into this service's venv
(see Setup below) — not as a separate HTTP service. It currently exposes `ClaimExtractor`,
`BM25Retriever`, `ClaimVerifier` and `verify_claim`, but **no single
`VerificationRequest -> VerificationReport` entry point** — checked in the repo before writing
`src/inkloom_api/engine/pipeline.py`, which is the missing integration, built directly from
those pieces. If Member 2 later publishes one pipeline function, that module should narrow to a
thin call into it instead.

**If no LLM provider is configured** (`OPENROUTER_API_KEY` / `INKLOOM_LLM_MODELS` unset),
`POST /api/reviews` does not fail — it writes one clearly-labelled stub finding
(`category: "stub"`, explanation prefixed `[STUB OUTPUT]`) so the full pipeline, storage and
response shape can be exercised and demoed without real credentials. **Stub mode is not real
verification** — a `[STUB OUTPUT]` finding proves the plumbing works, nothing about the
content; never treat it as an actual check against brand sources. See
`src/inkloom_api/engine/pipeline.py`.

**Span offsets are Unicode code points**, not UTF-16 code units — `finding.span.start`/`end`
index into `text` the same way Python's own string indexing does, matching Member 2's engine
convention exactly (`services/verification/CONTRACTS.md`, "Offsets"). A JavaScript client
highlighting that range must convert (e.g. `Array.from(text).slice(start, end).join("")`), not
index the string directly, whenever it may contain characters outside the Basic Multilingual
Plane (emoji, etc.) — plain indexing silently misaligns on those.

## Setup

```sh
cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pip install -e ../verification   # Member 2's engine, editable

# Local Postgres (requires Docker Desktop running):
docker compose up -d

cp .env.example .env   # fill in DATABASE_URL if you changed the compose defaults
.venv/Scripts/python -m alembic upgrade head

.venv/Scripts/python -m uvicorn inkloom_api.main:app --reload
# GET http://localhost:8000/health -> {"status": "ok"}
```

Run tests (DB-backed ones skip automatically if `DATABASE_URL` isn't set or Postgres isn't
reachable; the permission-table tests always run, no DB needed):

```sh
DATABASE_URL=postgresql+psycopg://inkloom:inkloom@localhost:5432/inkloom AUTH_SECRET_KEY=test-secret .venv/Scripts/python -m pytest
```

Try a login by hand once the server is running and a user exists (Phase 8 adds a seed script —
until then, insert one directly, e.g. via `python -c` using
`inkloom_api.auth.security.hash_password`):

```sh
curl -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "..."}'
curl http://localhost:8000/api/brands/<brand-id>/sources -H "Authorization: Bearer <access_token>"

curl -X POST http://localhost:8000/api/reviews -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"brand_id": "<brand-id>", "text": "The Lumen Bottle keeps drinks cold for 24 hours."}'
```

## Verification status

What has actually been run, versus only reviewed, as of Phase 3:

| Checked | Not yet checked (needs a live Postgres) |
|---|---|
| App imports, all routes register (`app.openapi()`) | The 4 DB-backed tenancy tests (`tests/test_tenant_scoping.py`) |
| Migration generates valid SQL (`alembic upgrade head --sql`) | A real `alembic upgrade head` / `downgrade base` |
| 18 DB-free permission unit tests pass | An actual `POST /api/reviews` call, with or without a real LLM provider |
| Engine imports resolve (`ClaimExtractor`, `BM25Retriever`, `ClaimVerifier`, `verify_claim`) | A real end-to-end run against OpenRouter |

Run the full suite once Postgres is reachable before treating any phase past 1 as done:
`DATABASE_URL=... AUTH_SECRET_KEY=... .venv/Scripts/python -m pytest`.

## Layout

| Path | Contents |
|---|---|
| `src/inkloom_api/main.py` | FastAPI app, middleware wiring, health check |
| `src/inkloom_api/config.py` | Settings loaded from the environment / `.env` |
| `src/inkloom_api/logging.py` | Structured logging, request ID middleware |
| `src/inkloom_api/errors.py` | Safe error responses (stable code, safe message, request ID) |
| `src/inkloom_api/db.py` | SQLAlchemy engine/session |
| `src/inkloom_api/statuses.py` | Every status string and role name, as the single source of truth |
| `src/inkloom_api/models/` | SQLAlchemy ORM models, one file per domain area |
| `src/inkloom_api/schemas.py` | API response DTOs (never return a SQLAlchemy model directly) |
| `src/inkloom_api/auth/security.py` | Password hashing, JWT creation/decoding |
| `src/inkloom_api/auth/permissions.py` | The role → permission table |
| `src/inkloom_api/auth/dependencies.py` | `get_current_membership` / `require_permission(...)`, the auth dependency every protected route uses |
| `src/inkloom_api/tenancy.py` | "Fetch by id, then check it resolves to this organisation" helpers |
| `src/inkloom_api/routers/` | Route modules (`auth`, `brands`, `reviews`) |
| `src/inkloom_api/engine/provider.py` | Picks a real `OpenRouterProvider` or signals "use the stub" |
| `src/inkloom_api/engine/pipeline.py` | Extraction → retrieval → verification → `Finding`/`EvidenceLink` rows; the stub fallback |
| `migrations/` | Alembic migrations |
| `tests/` | Tests against a real Postgres (see `docker-compose.yml`), plus DB-free permission unit tests |

## Open decisions (see `contract/README.md`)

- Membership role names (`submitter`, `source_manager`, `reviewer`, `approver`, `admin`) are
  confirmed (Phase 2).
- Auth (Phase 2): email + password, bcrypt-hashed, JWT bearer token scoped to one organisation
  per token. A user with more than one active membership gets the earliest-created one at login
  — documented limitation, see `src/inkloom_api/auth/security.py`.
- Answers proposed to Member 2's open integration questions 6-8 in `CONTRACTS.md` (tenant ID from
  the authenticated context, not the request body; this service generates and stores
  `request_id`; this service owns the validation error handler and strips input values).
- Analysis execution (Phase 3): synchronous, confirmed with the team. `POST /api/reviews` blocks
  until the review reaches a final state; no background job or polling yet.
- A brand with zero **approved** sources makes the review `failed` (not `needs_human_review`),
  with `error_summary` naming the problem — the engine itself refuses a request with no
  reference documents, and "nothing to check against" is a setup problem, not a content
  problem.
- `reviews.report_status` is not populated yet — Phase 3's adapter writes `Finding`/`EvidenceLink`
  rows directly rather than assembling a `VerificationReport`, since there was no single engine
  entry point to produce one (see the engine note above). Revisit if a later phase needs the raw
  report shape (e.g. for `result_cache`).
