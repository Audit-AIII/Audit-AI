# INKLOOM AI backend — API reference and setup

This answers two questions: **will the AI engine work right now**, and **exactly what do you
need to put in to make it work**. Then it documents every route.

## Will it work right now?

**Yes** — verified against a real Postgres database, 84 tests pass in one command (see
`README.md`, "Test"), and `scripts/seed.py` / `scripts/smoke_test.py` have both been run live
against it. The one thing not currently working in this environment's own `.env`: no configured
LLM provider (Gemini/Groq/OpenRouter/Ollama) is actually reachable right now — free-tier model
ids go stale (see `member3_backend/STATUS.md`, "What's left from you"). Without a working
provider, `POST /api/reviews` still returns `201` and completes, but every review gets one
fixed placeholder finding instead of a real one — see "Stub mode" below. **This is a safe
fallback, not a crash** — set up from scratch below if you don't already have `.env` in place.

## Setup, start to finish

### 1. Create `.env`

```sh
cd services/api
cp .env.example .env
```

Open `.env` and fill in:

- `AUTH_SECRET_KEY` — generate one:
  ```sh
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- `DATABASE_URL` — leave the default (`postgresql+psycopg://inkloom:inkloom@localhost:5432/inkloom`)
  if you use the provided `docker-compose.yml` unchanged.
- `OPENROUTER_API_KEY` and `INKLOOM_LLM_MODELS` — leave blank for now if you don't have a key
  yet; the server still runs, just in stub mode (see below). Fill these in once you have a key
  — see "Getting an OpenRouter key" below for exactly what to put there.

**Why `.env` alone is enough for the AI engine too:** `main.py` calls `load_dotenv()` before
anything else runs, which loads every key in `.env` into the real process environment — not just
the ones this app's own `Settings` class knows about. That matters because Member 2's engine
(`inkloom_verify.providers.openrouter`) reads `OPENROUTER_API_KEY` / `INKLOOM_LLM_MODELS`
directly from `os.environ`, not from anything this app passes it. (This wasn't wired until this
pass — `pydantic-settings`' own `.env` parsing only populates its declared fields, and never
touches `os.environ`, so without `load_dotenv()` a key placed in `.env` would silently never
reach the engine. Fixed in `main.py`; verified by hand — see the repo's commit history for
`main.py` around this doc's date if you want to see the exact check.)

### 2. Start Postgres

Needs Docker Desktop actually running (not just installed) — check with `docker ps` first.

```sh
docker compose up -d
```

### 3. Install dependencies and run migrations

```sh
cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"        # on macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pip install -e ../verification  # Member 2's engine, editable install

.venv/Scripts/python -m alembic upgrade head
```

### 4. Seed a demo user and brand to log in as

```sh
cd services/api
.venv/Scripts/python scripts/seed.py
```

Creates a demo organisation, a brand with two **approved** sources (a review needs at least one
to check content against — without one, every review for that brand comes back `failed` by
design, see "What `POST /api/reviews` can return" below), and five users, one per role (all
share one password, printed at the end). It also prints a `BRAND_ID` — keep it, you'll need it
for step 6. Idempotent: safe to re-run, no-ops if the demo org already exists (delete it first,
cascades, to reseed from scratch). See `services/api/README.md`, "Seed demo data", for what else
it creates. **Role must be one of:** `submitter`, `source_manager`, `reviewer`, `approver`,
`admin` (`admin` can do everything, see "Roles and permissions" below) — use the seeded admin
login while testing.

### 5. Run the server

```sh
.venv/Scripts/python -m uvicorn inkloom_api.main:app --reload
```

`GET http://localhost:8000/health` should return `{"status": "ok"}`. If it doesn't, Postgres
isn't reachable — go back to step 2.

Interactive API docs are auto-published at `http://localhost:8000/docs` (Swagger UI) and
`/redoc` — useful for trying requests by hand without `curl`.

### 6. Log in, then submit a review

```sh
# Login (seeded admin - see step 4; password is whatever scripts/seed.py printed)
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@seed.inkloom.demo", "password": "<seed.py's printed password>"}'
# -> copy "access_token" from the response

TOKEN="<paste access_token here>"
BRAND_ID="<paste BRAND_ID from step 4 here>"

curl -X POST http://localhost:8000/api/reviews \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"brand_id\": \"$BRAND_ID\", \"text\": \"The Lumen Bottle keeps drinks cold for up to 24 hours. It is made from 90% recycled steel.\"}"
```

- **No `OPENROUTER_API_KEY` set** → `201`, `status: "needs_human_review"`, one finding with
  `category: "stub"` and an explanation starting `[STUB OUTPUT]`. This proves the whole pipeline
  (auth → tenancy → storage → response shape) works; it is not a real verification.
- **`OPENROUTER_API_KEY` set correctly** → the real engine runs: claims get extracted from the
  text, each is checked against the brand's approved source text, and you get real
  `supported`/`contradicted`/`unverified` findings with evidence quotes.

## Getting an OpenRouter key (for real AI checks)

1. Sign up and create a key at [openrouter.ai/keys](https://openrouter.ai/keys). Put it in
   `.env` as `OPENROUTER_API_KEY`.
2. Pick 1-5 model ids from [openrouter.ai/models](https://openrouter.ai/models) that support
   **structured outputs** (JSON schema mode) — filter by that capability on the models page.
   Member 2's team's stated preference (`services/verification/PROMPTS.md`): a Gemini Flash
   model first, a Llama model as fallback. **Copy the exact current ids from that page** — they
   change over time and none are hard-coded anywhere in this repo, by design. As of this
   writing, ids of that shape look like `google/gemini-2.5-flash` and
   `meta-llama/llama-3.1-8b-instruct`, but confirm on the models page before using them.
3. Put them comma-separated in `.env` as `INKLOOM_LLM_MODELS`, e.g.:
   ```
   INKLOOM_LLM_MODELS=google/gemini-2.5-flash,meta-llama/llama-3.1-8b-instruct
   ```
4. Restart the server (env vars are read once at process start).

**Cost and data note:** once a key is set, submitted content is sent to OpenRouter and on to
whichever model answers (`INKLOOM_LLM_DATA_COLLECTION=deny`, the default, limits this to
providers that don't retain prompt data, but the content still leaves the machine). Each call
costs whatever OpenRouter charges for the model used. Don't point this at confidential content
until that's acceptable for your use.

## What `POST /api/reviews` can return

Analysis is **synchronous** — the request blocks until one of these three outcomes is reached,
and the response already reflects it:

| `status` | When | `findings` |
|---|---|---|
| `completed` | Real engine ran; every claim came back `SUPPORTED` (or there was nothing to check) | Zero or more, all `supported` |
| `needs_human_review` | Real engine ran and at least one claim needs a look, **or** no LLM provider is configured (stub mode) | Real findings, or one `category: "stub"` placeholder |
| `failed` | The brand has no approved source to check against, or claim extraction itself could not run | Empty, with `error_summary` explaining why |

`failed` here is a normal `201` response with `status: "failed"` in the body — not an HTTP error.
The review resource was created; it just has nothing usable in it.

## Full route reference

All routes except `/health` and `/api/auth/login` require `Authorization: Bearer <access_token>`.

### `GET /health`
No auth. `200 {"status": "ok"}` if the database is reachable.

### `POST /api/auth/login`
No auth. Body: `{"email": "...", "password": "..."}`.

**200:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {"id": "...", "email": "...", "display_name": null},
  "organisation": {"id": "...", "name": "Acme Corp", "slug": "acme"},
  "role": "admin"
}
```
**401** (same message whether the email is unknown, the password is wrong, or the account has no
active organisation membership — deliberately indistinguishable):
```json
{"error": {"code": "UNAUTHENTICATED", "message": "invalid email or password", "request_id": "..."}}
```

A token is scoped to **one organisation**, decided at login. A user in more than one
organisation gets whichever membership was created first — no org switcher yet.

### `GET /api/auth/me`
Returns `{"user", "organisation", "role"}` (no token field) for the caller's current session.
Use this to restore a session on page load rather than trusting a cached copy — a membership can
be deactivated between requests.

### `GET /api/brands/{brand_id}/sources`
Any active member of the organisation may call this (no specific permission required). Returns
a list of the brand's `BrandSource` rows:
```json
[{"id": "...", "brand_profile_id": "...", "title": "Product spec", "status": "approved", "sensitivity": "normal", "created_at": "...", "updated_at": "..."}]
```
`brand_id` belonging to another organisation returns `404`, identical to a `brand_id` that
doesn't exist at all — this never reveals whether another tenant's data exists.

### `POST /api/reviews`
Body: `{"brand_id": "...", "title"?: "...", "text": "..."}` (`text` 1-100,000 characters).
Returns `201` with the full `Review` shape below (see "What `POST /api/reviews` can return"
above for what `status` ends up as). `brand_id` from another organisation: `404`.

### `GET /api/reviews/{review_id}`
Returns the same `Review` shape. Scoped to the caller's organisation (`404` for any other
tenant's review, same indistinguishable-404 rule as brands).

**Review shape** (both routes return this):
```json
{
  "id": "...",
  "content_version_id": "...",
  "status": "needs_human_review",
  "report_status": null,
  "engine": {"provider": "openrouter", "model_id": "google/gemini-2.5-flash", "prompt_version": "extract-claims-v1", "contract_version": "0.1.0"},
  "error_summary": null,
  "started_at": "...", "completed_at": "...", "created_at": "...", "updated_at": "...",
  "findings": [
    {
      "finding_id": "...",
      "category": null,
      "severity": "high",
      "original_text": "It is made from 90% recycled steel.",
      "span": {"start": 55, "end": 90},
      "check_type": "retrieval",
      "explanation": "P1 gives 70% recycled content, not 90%.",
      "verification_status": "contradicted",
      "suggested_correction": "It is made from 70% recycled steel.",
      "requires_human_review": true,
      "evidence": [
        {"id": "...", "source_id": "...", "source_version_id": "...", "quote": "70% recycled content", "relation": "contradicts"}
      ]
    }
  ]
}
```
`span` offsets are Unicode **code points** into the submitted `text`, not UTF-16 code units — a
JavaScript client highlighting text must account for that (see `contract/README.md`, "Offsets").

### Error shape (every route, on failure)
```json
{"error": {"code": "NOT_FOUND", "message": "brand not found", "request_id": "6b2e9a1c..."}}
```
| HTTP | `code` | Meaning |
|---|---|---|
| 401 | `UNAUTHENTICATED` | No token, invalid/expired token, or a membership no longer active |
| 403 | `FORBIDDEN` | Authenticated, but the role lacks the needed permission |
| 404 | `NOT_FOUND` | Doesn't exist, or belongs to another organisation — indistinguishable on purpose |
| 422 | `VALIDATION_ERROR` | Request body/params failed validation; lists field locations only, never the submitted value |
| 500 | `INTERNAL_ERROR` | Unexpected server error |

Every response — success or error — carries `X-Request-ID`, echoed in `error.request_id` too.
Match that to a server log line if something needs debugging.

## Roles and permissions

| Role | submit | manage_sources | review | approve | administer |
|---|---|---|---|---|---|
| `submitter` | yes | | | | |
| `source_manager` | | yes | | | |
| `reviewer` | | | yes | | |
| `approver` | | | yes | yes | |
| `admin` | yes | yes | yes | yes | yes |

Neither route implemented so far (`GET /api/brands/{id}/sources`, `POST`/`GET /api/reviews`)
requires a specific permission beyond being an active member — this table matters starting
Phase 4+ (managing sources, approving content versions).

## Known gaps (don't be surprised by these)

- **This route reference describes Phases 1-3 only** — Phases 4-7 added routes (brand source
  upload/approve/withdraw/new-version, content new-version/history, content-version approve/
  request-changes, review rerun) that aren't documented in "Full route reference" below yet.
  See `services/api/README.md`'s architecture table and `member3_backend/STATUS.md` for what
  those actually do until this file catches up.
- **`ReviewOut` never exposes `content_item_id`**, only `content_version_id` - a real gap found
  while building `scripts/smoke_test.py` (Phase 8). Creating a new content version needs the
  item id; nothing in this flow's responses carries it today. See `README.md`'s "Known
  limitations".
- **No organisation switcher**, **no polling** (synchronous only), **no background jobs** —
  all explicit, confirmed simplifications for this phase, not oversights. See
  `services/api/README.md`'s "Open decisions" for the full list and the reasoning behind each.
