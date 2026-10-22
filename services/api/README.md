# INKLOOM AI backend

Member 3's service: database, auth, tenant isolation, API, orchestration, versioning, approval
state machine, audit, failure handling, and the LLM provider adapter. See
[`../../member3_backend/00_CONTEXT.md`](../../member3_backend/00_CONTEXT.md) for the product
context and the shared contract this backend enforces, and
[`../../contract/README.md`](../../contract/README.md) for the status strings, role names and
example payloads shared with Members 1 and 2.

**Status:** Phase 1 (foundation and contract) is done: project skeleton, config, health check,
structured logging with request IDs, the full migration set, and `contract/`. Auth, the actual
routes and the engine wiring are later phases — see `00_CONTEXT.md`'s phase order.

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

Run tests (they skip automatically if `DATABASE_URL` isn't set or Postgres isn't reachable):

```sh
DATABASE_URL=postgresql+psycopg://inkloom:inkloom@localhost:5432/inkloom .venv/Scripts/python -m pytest
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
| `migrations/` | Alembic migrations |
| `tests/` | Tests against a real Postgres (see `docker-compose.yml`) |

## Open decisions (see `contract/README.md`)

- Membership role names (`submitter`, `source_manager`, `reviewer`, `approver`, `admin`) are
  confirmed (Phase 2).
- Auth (Phase 2): email + password, bcrypt-hashed, JWT bearer token scoped to one organisation
  per token. A user with more than one active membership gets the earliest-created one at login
  — documented limitation, see `src/inkloom_api/auth/security.py`.
- Answers proposed to Member 2's open integration questions 6-8 in `CONTRACTS.md` (tenant ID from
  the authenticated context, not the request body; this service generates and stores
  `request_id`; this service owns the validation error handler and strips input values).
