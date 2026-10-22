# INKLOOM AI backend

Member 3's service: database, auth, tenant isolation, API, orchestration, versioning, approval
state machine, audit, failure handling, and the LLM provider adapter. See
[`../../member3_backend/00_CONTEXT.md`](../../member3_backend/00_CONTEXT.md) for the product
context and the shared contract this backend enforces, and
[`../../contract/README.md`](../../contract/README.md) for the status strings, role names and
example payloads shared with Members 1 and 2.

**Status:** Phase 1 (foundation and contract) and Phase 2 (auth and tenant scoping) are built:
project skeleton, migrations, `contract/`, email+password login issuing a JWT scoped to one
organisation, the auth dependency (re-checks the membership fresh from the database on every
request), the permission table, the tenant-scoping helper, and one protected route
(`GET /api/brands/{id}/sources`) proving the pattern end to end. **Not yet verified against a
live database** — Docker wasn't up in this environment; the migration's generated SQL was
checked offline, and the permission-table unit tests pass, but the DB-backed tenancy tests
(`tests/test_tenant_scoping.py`) have only been reviewed, not run. Run them once Postgres is
reachable before treating Phase 2 as done. The remaining routes and the engine wiring are later
phases — see `00_CONTEXT.md`'s phase order.

The engine (Member 2, [`services/verification`](../verification)) is called in-process: it is a
plain importable Python package, not a separate HTTP service. See
[`services/verification/CONTRACTS.md`](../verification/CONTRACTS.md) for its request/report
shapes, which this backend's `reviews`/`findings`/`evidence_links` tables are built to receive.

## Setup

```sh
cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # on macOS/Linux: .venv/bin/python

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
```

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
| `src/inkloom_api/routers/` | Route modules (`auth`, `brands`) |
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
