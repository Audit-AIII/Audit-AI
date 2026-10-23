# Frontend ↔ backend integration notes

For Member 3 (backend). Written by Member 1 (frontend) while wiring the workspace to `services/api`.
Nothing in `services/` was changed. Each item below is for you to decide.

**How this was checked.**
1. The typed client (`lib/api/types.ts`) was compared field by field with
   `services/api/src/inkloom_api/schemas.py`, `statuses.py`, `errors.py`, the routers, `API.md`
   and `contract/`.
2. **Live (2026-10-23)**: against a local backend (Postgres 16, all 8 migrations, `seed.py`,
   no LLM key, so stub mode). `qa/api-probe.mjs` called every route the frontend uses, plus the
   error cases, and compared response keys with the types. **Every response matched: no missing
   or extra fields.** `qa/api-live.mjs` then ran the full browser flow on `localhost:3000`
   (sign in → sources → submit → result → refresh → 404 → expired token) with no CORS or page
   errors.
3. `qa/api-e2e.mjs` runs the same screens against a fake server with real (non-stub) findings,
   because stub mode can't produce those.

**Not checked live yet:** real findings (supported / contradicted / unverified with evidence).
They need an LLM key, and the seeded reviews are stubs too.

## 1. API.md is behind the code

The frontend follows the code (`schemas.py`). Please update `API.md`, or tell me if the code is wrong.

| What | `API.md` | Code (`schemas.py` / `errors.py` / `statuses.py`) |
|---|---|---|
| `Review` fields | no `served_from_cache`, no `required_reviewer_role` | both present on every review |
| `BrandSource` fields | no `source_type`, no `latest_version` | both present (`null` for seeded sources) |
| Roles | 5 roles | 7: also `legal_reviewer`, `brand_manager` |
| Error codes | 401 / 403 / 404 / 422 / 500 | also **409 `CONFLICT`** (Idempotency-Key reused with a different body) and **429 `RATE_LIMITED`** (submission limits) |
| `Idempotency-Key` header on `POST /api/reviews` | not mentioned in the route reference | supported; the frontend now sends one per draft |
| Stub explanation | says only `OPENROUTER_API_KEY` | text names Gemini / Groq / OpenRouter / Ollama, and can end with ` Reason: …` |
| `report_status` | example shows `null` | `contract/examples/review_success.json` shows `"COMPLETED"` (upper case, unlike every other status). What values can it take, and what does it mean? |
| `engine.prompt_version` | `extract-claims-v1` | contract example says `verify-v1`. Display only, but which is right? |

## 1b. Seen on the live backend, not in the docs

| What | Docs | Live |
|---|---|---|
| `engine` in stub mode | `API.md` example implies a real engine; I had assumed `null` | `{"provider": "stub-unconfigured", "model_id": null, "prompt_version": null, "contract_version": "0.1.0"}`. The frontend now also treats `provider` starting with `stub` as a placeholder. Please confirm this value is stable. |
| `required_reviewer_role` in stub mode | – | `"brand_manager"` even though nothing was really checked. Should routing apply to a placeholder? |
| Seeded reviews | `API.md`: seed creates sources and users | Also creates 4 sample reviews, and all of them are stubs without a key |
| Seeded users | "five users, one per role" | **seven** (also `legal_reviewer`, `brand_manager`) |
| `X-Request-ID` | "every response carries `X-Request-ID`" | Sent, but **not readable from browser JavaScript** (CORS `expose_headers` not set). The frontend uses `error.request_id` from the body instead, so success responses have no readable request id. Add `expose_headers=["X-Request-ID"]` if you want it. |
| Malformed id in a path (`/api/brands/not-a-uuid/sources`) | 404 | **422** `invalid request: path.brand_id`. The frontend shows both as "no brand with that ID". |
| Spans | code points | Confirmed: an emoji text of 92 code points / 93 UTF-16 units got `span.end = 92` |
| Idempotency | – | Confirmed: same key + same body replays the same review id; same key + other body → 409 `CONFLICT` |
| Seeded sources | – | `source_type: null`, `latest_version: 1` |

## 2. Fields the frontend needs that the backend does not return

Ordered by how much they block the demo.

1. **No way to find the caller's brands.** `login` and `/me` return no brand, and there is no
   `GET /api/brands`. The frontend can't discover a `brand_id`, so for now the user pastes it once
   on the Sources stage (the seed script prints it). Proposal: `GET /api/brands` →
   `[{id, name}]` for the caller's organisation, or a `brands` list on `/me`.
2. **`Review` doesn't include the submitted `text`.** Highlighting needs the full text plus the
   spans. The frontend keeps its own copy in the browser that sent it, so a refresh works. But
   opening a review on another device, or from someone else's link, shows the findings without
   highlights. Proposal: add `text` (and `title`) to `Review`, or a `GET /api/content-versions/{id}`
   that returns it.
3. **`Review` doesn't say which brand or content item it belongs to.** Needed to show "checked
   against brand X" and to create a new version (`content_item_id`, already in API.md "Known
   gaps").
4. **Evidence has `source_id` but no source title.** To show "From: Product spec v1" the
   frontend would have to load the brand's sources and match ids, which needs the brand id (item 1).
   Proposal: add `source_title` and `source_version_number` to each evidence item.
5. **The stub is detected by the string `category == "stub"`.** This works, and the UI shows it
   as a placeholder rather than a verified result. An explicit flag would be safer against a real
   category ever being called "stub", for example `engine.provider = "stub"` or
   `is_placeholder: true` on the finding. Today `engine` is `null` in stub mode.
6. **`category` is often `null`** for real findings, so the UI falls back to `check_type`
   ("Retrieval") as the check name. A user-facing check name (Facts / Claims / Tone …) would read
   better.
7. **No `GET /api/reviews` list.** There is no way to show "your recent reviews" after the browser
   forgets the last id.
8. **No token expiry in the login response** (`expires_in`). Tokens last
   `AUTH_TOKEN_TTL_MINUTES`, 720 (12 h) by default, but the client isn't told. The frontend only
   learns a token expired when a call returns 401. That is handled: it signs out and sends the
   user to sign in with a "session ended" note.
9. **No sign-up route.** The "Create account" page now says accounts are created by an admin
   instead of pretending to make one.

## 3. Setup notes

- **CORS:** kept at the default `http://localhost:3000`; the frontend dev server runs on 3000
  (`npm run dev`), and the QA scripts now use 3000 too. Confirmed live: a preflight from :3000 is
  allowed (`authorization, content-type, idempotency-key`), and one from :3100 is rejected (400).
- **Local Postgres port:** on this machine a native PostgreSQL service already uses 5432, so the
  backend's database ran in Docker on **5433** (same image and credentials as
  `docker-compose.yml`, which was not edited), with `DATABASE_URL` in the git-ignored `.env`
  pointing there. If `docker compose up` fails with "port is already allocated", that's why.
- **Frontend env:** only `NEXT_PUBLIC_API_URL` (see `.env.example`). No keys or backend secrets
  ever go in the frontend. Anything `NEXT_PUBLIC_*` is visible to every browser.

## 4. How the frontend handles the contract

- **Errors:** one place, `lib/api/client.ts`. Every failure becomes an `ApiError` with
  `status`, `code`, `message` and `requestId`, and the screens show a plain-language message.
  - 401 on an authenticated call signs out and redirects to `/login?expired=1`.
  - Login's own 401 shows "email and password don't match".
  - 404 is never phrased as "doesn't exist", because it may be another organisation's data.
  - 422 shows the field locations from the message.
  - The request id is shown with its original case on the review error screen, so it can be
    matched to a server log line.
- **Spans:** converted from code points to UTF-16 before any slicing (`lib/text/codepoints.ts`).
  Tested with emoji and flag characters (`qa/unit/codepoints.test.mts`).
- **Statuses:** `unverified` is always shown as "Not proven yet", never as false.
  `conflicting_sources` and `not_applicable` have their own labels. Unknown future values are
  shown as text instead of crashing.
- **Results survive a refresh:** the Review stage reads the id from `?id=` and calls
  `GET /api/reviews/{id}`.
