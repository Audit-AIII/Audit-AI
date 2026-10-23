# Self-serve onboarding — handoff to Member 1

What this gives the frontend: a visitor signs up with any email and password and immediately has
a working private workspace — an organisation, an `admin` membership and a starter brand, all
created in one transaction. They upload one brand-fact file (approved in the same step, so it's
usable right away), then check a piece of draft content against it — pasted text or an uploaded
file. **The user never needs to know or handle a brand id**: `register` returns the starter
brand's full `BrandOut`, and `GET /api/brands` always lists it first.

Routes below are additive — no existing route, field name or status code changed. `ReviewOut`
gained five new optional fields (default `null`) that existing callers can simply ignore.

## The flow

1. `POST /api/auth/register` → get back a bearer token, the new organisation, and `brand.id`.
2. `POST /api/brands/{brand_id}/sources` with `approve=true` → upload a PDF/DOCX/TXT fact sheet,
   already approved — one call, not upload-then-approve.
3. `POST /api/reviews/upload` (or `POST /api/reviews` with pasted text) → check a draft against
   that brand's approved sources. Returns the same `Review` shape as every other review route.

Everything else (brand list/create, existing review/content/approval routes) works exactly as
documented in `services/api/API.md`.

## `POST /api/auth/register`

Public — no `Authorization` header, no existing account needed.

**Request body:**
```json
{
  "email": "ada@example.com",
  "password": "correct-horse-battery",
  "display_name": "Ada Lovelace",
  "organisation_name": "Ada's Studio",
  "brand_name": "Ada's Brand"
}
```
Only `email` and `password` are required. Any of the other three may be omitted or sent blank
(`""` is treated the same as omitting it):

| Field | Default when omitted/blank |
|---|---|
| `display_name` | `null` |
| `organisation_name` | `"<display_name or the email's local-part>'s workspace"` |
| `brand_name` | `"My brand"` |

`password`: 8–72 **bytes** (bcrypt's own limit — a password with multi-byte characters can be
under 72 characters but still over 72 bytes; count bytes, not characters, if you add client-side
validation). `email`: any syntactically valid address works, no verification step exists (see
"Known limits" below).

Sending `role` or `organisation_id` in the body does nothing — they aren't fields this endpoint
reads. The caller is always made `admin` of a **brand-new** organisation; there is no way to join
an existing one through this route.

**201:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 43200,
  "user": {"id": "...", "email": "ada@example.com", "display_name": "Ada Lovelace"},
  "organisation": {"id": "...", "name": "Ada's Studio", "slug": "ada-s-studio-3f9a1c2b"},
  "role": "admin",
  "brand": {
    "id": "...",
    "name": "Ada's Brand",
    "description": null,
    "approved_source_count": 0,
    "created_at": "2026-01-01T00:00:00Z"
  }
}
```
`expires_in` is seconds until the token expires (also now returned by `POST /api/auth/login`,
previously absent there too). `slug` is generated server-side — a URL-safe version of the
organisation name plus 8 random hex characters, so two people naming their workspace the same
thing never collide.

**Errors:**
| Status | `code` | When |
|---|---|---|
| 409 | `CONFLICT` | `"an account with this email already exists; sign in instead"` — email match is case-insensitive |
| 422 | `VALIDATION_ERROR` | Bad email syntax, password under 8 chars/over 72 bytes/blank, or a name field over 200 chars |
| 429 | `RATE_LIMITED` | More than 5 registrations from the same IP in 10 minutes (defaults; see `services/api/.env.example`) |

Email matching is case-insensitive both ways: `Ada@Example.com` and `ada@example.com` collide,
and logging in with either case works once registered (emails are stored lower-cased).

## `POST /api/brands/{brand_id}/sources` — new `approve` field

Unchanged except one new optional multipart field:

```
title: "Fact Sheet"
approve: "true"          # new; defaults to "false" (unchanged behaviour)
file: <PDF/DOCX/TXT>
```
`approve=true` creates the source already `"approved"` instead of `"draft"` — skips a separate
call to `.../approve`. Requires the same `manage_sources` permission the upload itself already
requires (so this never grants anything new); `admin` (what `register` always creates) always
holds it.

## `GET` / `POST /api/brands` — new

**`GET /api/brands`** — any active member. Lists every brand in the caller's organisation,
oldest first (the sign-up brand from `register` is always `[0]`):
```json
[
  {"id": "...", "name": "My brand", "description": null, "approved_source_count": 1, "created_at": "..."},
  {"id": "...", "name": "Second Brand", "description": "...", "approved_source_count": 0, "created_at": "..."}
]
```

**`POST /api/brands`** — requires `manage_sources`. Body: `{"name": "...", "description"?: "..."}`
(`name` 1–200 chars, not blank; `description` up to 2000 chars, blank → `null`). `201` with the
same `BrandOut` shape above. `409 CONFLICT` (`"a brand with this name already exists"`) if the
organisation already has a brand with that exact name.

## `POST /api/reviews/upload` — new

A file-upload sibling of `POST /api/reviews`, for people who'd rather upload a draft than paste
text. Same auth, same rate limit, same `Idempotency-Key` support, same `Review` response shape —
everything in `services/api/API.md`'s "`POST /api/reviews`" section applies here too.

```
brand_id: "..."          # form field, required
title: "Q1 launch copy"  # form field, optional — defaults to the filename without its extension
file: <PDF/DOCX/TXT>      # same three types as brand sources
```

The uploaded file's bytes are **never stored** — only the extracted text, as the content item's
first version. A file whose extracted text is empty, unreadable, or over 100,000 characters is
rejected with `422` (same limits `source_upload.py` already enforces for brand sources, plus the
same 100,000-character cap `POST /api/reviews`'s `text` field has always had).

**`Review` response — five new fields** (present on `/api/reviews`, `/api/reviews/upload`, and
`GET /api/reviews/{id}` alike; `null` on any review from before this change, so existing parsers
don't need to change anything):
```json
{
  "...": "... every existing field, unchanged ...",
  "content_item_id": "...",
  "brand_id": "...",
  "title": "my-draft",
  "version_number": 1,
  "text": "Draft: the Lumen Widget weighs 150 grams."
}
```
This closes a gap `scripts/smoke_test.py` had previously documented and worked around (fetching
`content_item_id` via a direct DB query) — `POST /api/content/{content_item_id}/versions` (new
version of existing content) can now be called straight from a review response.

## Security notes

- Registration rate limiting is keyed on `request.client.host` only — **never**
  `X-Forwarded-For` (trivially spoofable by the caller). If this is deployed behind a reverse
  proxy that terminates TLS, `request.client.host` will be the proxy's address, not the visitor's
  — same single-process limitation `rate_limit.py` already documents for submission limits.
- A registered user's password is bcrypt-hashed exactly like every other user's (`auth/security.py`
  — nothing special about this path).
- Every register creates its own organisation — there is no concept of "join my teammate's
  workspace" here (see "Known limits").
- `account.registered`'s audit event records only `{"brand_id": ...}` — never the email or name,
  consistent with every other audit event in this system (`audit.py`'s own rule).

## Known limits (confirmed scope, not oversights)

- **No email verification.** Any syntactically valid address works; nothing is sent to it.
- **No password reset.** Lost password = no recovery path today.
- **No invites / no "join an existing organisation."** Every registration creates a brand-new
  organisation; there's no way for a second person to land in the first person's workspace
  except by someone manually inserting a `Membership` row.
- **The registering user can always approve their own content.** They're `admin`, which holds
  every permission — there's no second reviewer in a brand-new, one-person workspace. This is
  the same tradeoff every other `admin` membership already has in this system, not new.
- **Scanned (image-only) PDFs extract no text** and are rejected with `422` — same limitation
  `source_upload.py` already has for brand sources; nothing added here is a new PDF parser.
