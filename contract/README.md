# INKLOOM AI shared contract (draft, v0.1.0)

Owned by Member 3 (backend). This is what Members 1 (frontend) and 2 (engine) read to avoid
guessing field names, status strings or role names. It describes the **backend's API layer** —
what `GET /api/reviews/{id}` and friends return to the frontend. It is a different, higher-level
vocabulary than Member 2's engine contract
([`services/verification/CONTRACTS.md`](../services/verification/CONTRACTS.md)): the backend
calls the engine in-process, then maps its `Verdict`/`ReportStatus` onto the status strings below
before anything reaches the frontend. The engine's contract is not re-exported to the frontend
directly.

**Status: draft, Phase 3.** Nothing here is final until Members 1 and 2 have reviewed it. Items
under [Open decisions](#open-decisions) are this member's proposal, not yet confirmed.

## Status strings

These come from the shared contract values ([`docs/backend.md`](../docs/backend.md)) and are enforced as Postgres CHECK
constraints in [`services/api/src/inkloom_api/statuses.py`](../services/api/src/inkloom_api/statuses.py),
which is the single source of truth. This file is hand-maintained to match it — there is no
generator (unlike Member 2's `json_schema.py`) — so if a value changes there, update it here too.

| Enum | Values |
|---|---|
| `verification_status` | `supported`, `contradicted`, `unverified`, `conflicting_sources`, `not_applicable` |
| `severity` | `low`, `medium`, `high`, `critical` |
| `evidence_relation` | `supports`, `contradicts`, `context` |
| `review_status` (`reviews.status`) | `draft`, `queued`, `analysing`, `completed`, `needs_human_review`, `changes_requested`, `approved`, `rejected`, `failed`, `source_changed` |
| `check_type` | `rule`, `retrieval`, `semantic` |
| `brand_source_status` | `draft`, `approved`, `superseded`, `archived` |
| `brand_source_sensitivity` | `normal`, `confidential` |
| `approval_action` | `approved`, `rejected`, `changes_requested` |

**`completed` never means approved.** A review reaching `completed` only means the engine
finished; a human must still act via `approve` / `request-changes` to reach `approved` /
`changes_requested`. See the governance invariants in [`docs/backend.md`](../docs/backend.md).

**Missing evidence means `unverified`, never `false`.** A finding with no supporting or
contradicting evidence must use `verification_status = unverified`, not `contradicted`.

## Accounts and roles (individual-user mode, 2026-10-24)

InkLoom is an **individual-user app**: one email = one private account, and each account can own
several brands. There are no teams, invites, admins-vs-others or reviewer tiers. A user sees only
their own brands, sources, content and reviews; any other account's id answers `404`,
indistinguishable from an id that doesn't exist.

Under the hood an account is an `organisation` with exactly one `membership`. Nothing in the API
shape changed:

- `POST /api/auth/register` creates the account and returns `role: "admin"`, which now simply
  means **account owner**. `GET /api/auth/me` and `POST /api/auth/login` return the same.
- Roles no longer grant or restrict anything: every active membership holds every permission
  (`services/api/src/inkloom_api/auth/permissions.py`). The other role names (`submitter`,
  `source_manager`, `reviewer`, `approver`, `legal_reviewer`, `brand_manager`) are still valid
  values of the column so old rows need no migration, but they behave exactly like `admin`.
- **Risk-based routing is off.** Every new review has `required_reviewer_role: null` (the UI
  shows that as "Any approver"). A review written before this change may still carry
  `"legal_reviewer"`/`"brand_manager"`; it no longer restricts who can approve.
- The user approves their own content ("ready to publish") with
  `POST /api/content-versions/{id}/approve`, or sends it back with `.../request-changes`. The
  approval guards that make sense for one person all remain (`409 CONFLICT`): the review must
  be finished (`completed`/`needs_human_review`), the version must be the current one, and no
  source the review cited may have been withdrawn or replaced since it ran.
- A `403 FORBIDDEN` for a missing permission can no longer happen for an active account.

## Finding and Review schema

JSON Schema: [`schemas/finding.schema.json`](schemas/finding.schema.json),
[`schemas/review.schema.json`](schemas/review.schema.json). A `Review` embeds its `findings`;
each `Finding` embeds its `evidence`. These describe the response body of `GET /api/reviews/{id}`.

Field names match the backend's `findings`/`evidence_links` tables ([`docs/backend.md`](../docs/backend.md),
"Shared contract values") exactly: `finding_id`, `category`, `severity`, `original_text`, `span` (`{start, end}`,
not separate `span_start`/`span_end` — collapsed into one object for the API response, same shape
as the engine's `SourceSpan`), `check_type`, `explanation`, `verification_status`,
`suggested_correction`, `requires_human_review`. Evidence: `source_id`, `source_version_id`,
`quote`, `relation`.

**Offsets.** `span.start`/`span.end` are half-open `[start, end)` Unicode code point offsets into
the content version's `text` — the same convention Member 2's engine uses
(`CONTRACTS.md`, "Offsets"; see integration question 1 below). They are **not** UTF-16 code
units, so a JavaScript frontend highlighting text must convert
(`Array.from(text).slice(start, end).join("")`), not index `text` directly, when the text
contains characters outside the Basic Multilingual Plane (emoji, etc).

**Fields added 2026-10-24 (all additive; existing fields unchanged).** On `Review`:
`brand_name` (alongside the earlier `content_item_id`, `brand_id`, `title`, `version_number`,
`text`). On each evidence item: `source_title`, `source_version_number` (the document version the
quote was taken from). `category` is now filled on real runs: `contradicted_claim`,
`unsupported_claim` (unverified - no evidence either way), `supported_claim`, `engine_error` (that
claim could not be checked); `stub` still marks the no-provider placeholder. `suggested_correction`
is the **whole `original_text` rewritten** (swap it in with `draft.replace(original_text,
suggested_correction)`); it is an evidence-backed, re-verified fix for contradicted claims only. An
unverified claim's softened wording is in the separate **`safer_wording`** field (not evidence-backed:
label it so; `null` when the backend's rule check refuses it). Both are only ever suggestions.
`verification_status` `conflicting_sources` (approved documents disagree) is now used.
`BrandOut` (`GET /api/brands`) gained `review_count`, `open_review_count` (reviews waiting for the
user's decision) and `last_review_at`.

## Rule findings and brand rules (2026-10-24, additive)

For Member 1 (Chahit). Member 2's terminology / compliance / accessibility rules now run on every
review. Full shapes: `services/api/API.md` ("Brand rules" and "Rule findings"). What the UI needs:

- A **rule finding** has `check_type: "rule"`, `category` `terminology` | `brand_compliance` |
  `accessibility` (**new values — the UI needs labels**), `verification_status: "not_applicable"`
  (not a claim verdict: don't render it as supported/contradicted), and new fields `rule_id`,
  `rule_type`, `scope`, `suggestion_basis`, `source_ids` (all `null` on claim findings).
- `scope: "document"` means something is missing; show it as about the whole draft, not the
  highlighted first line.
- `suggested_correction` works as for claims (`draft.replace(original_text, suggested_correction)`);
  label it by `suggestion_basis`: brand rule vs. approved document.
- On the review, `rules_status` (`complete` | `incomplete` | `not_applied` | `null`) and
  `rule_checks`. A check with status `not_checkable` must read "not checked", never "passed";
  `incomplete` / `not_applied` mean the draft must not be shown as rule-clean.
- `GET` / `PUT /api/brands/{id}/rules` to view and edit a brand's rules (a rules editor is new UI).

## Intent-lock, Dismiss and comments (2026-10-24, additive)

For Member 1 (Chahit). Full shapes: `services/api/API.md`.

- **Intent-lock:** read and write locks with `GET` / `PUT /api/content-versions/{id}/locks` instead of
  `localStorage` (`lib/additions/locks.ts`). The review has `locked_phrases`. A finding with
  `withheld_by_intent_lock: true` had a suggestion that would break a lock: say "Suggestion hidden: it
  would change locked text. Re-check to get a new one."
- **Dismiss:** `POST /api/findings/{id}/dismiss` and `.../restore`. Show `dismissal` as "Dismissed by
  you" with the note; never as supported or verified. The review's status doesn't change.
- **Comments:** `GET` / `POST /api/findings/{id}/comments`; `comment_count` on each finding.

## Routes for the new UI pages (2026-10-24)

Full shapes and example JSON: `services/api/API.md`.

| Route | Page | Notes |
|---|---|---|
| `GET /api/reviews?status=&brand_id=&limit=&offset=` | Review queue | Plain JSON array of full `Review` objects, newest first; `status` repeatable; limit 1-100 (default 50) |
| `GET /api/analytics/brand-risk?brand_id=&days=` | Insights | `{top_categories, median_turnaround_minutes, re_review_rate, queue_age_minutes: {median, oldest}, sample_size}`; zero data -> `[]`, `null`s, `0` |
| `GET /api/evaluations/latest` | Trust Scorecard | 404 until a run exists ("not available yet") |
| `POST /api/evaluations` | Trust Scorecard "Run evaluation" | 201 `{catch_rate, false_positive_rate, per_check, sample_size, run_at, ...}`; 409 no provider or too many provider failures (message is user-readable); 429 more than once per 10 minutes |

## Submitting a review (Phase 3)

- **`POST /api/reviews`** — body `{"brand_id", "title"? , "text"}`. `brand_id` must be a brand
  in the caller's own organisation (404 otherwise, same as any other cross-tenant lookup).
  `text` is 1-100,000 characters (`inkloom_verify`'s own limit).
- **Synchronous.** Confirmed with the team for this phase: the request blocks until analysis
  finishes, and the response body is a full `Review` (same shape as `GET /api/reviews/{id}`),
  already in its final `status` — `completed`, `needs_human_review`, or `failed`. There is
  nothing to poll yet; a later phase may move this to `queued` + polling for longer content.
- **`failed` is a real, visible outcome**, not a 500. Two cases produce it today: the brand has
  no **approved** brand source to check against, or claim extraction itself could not run. Both
  come back as `201` with `status: "failed"` and a safe `error_summary` — the review resource
  was still created, it just has nothing usable in it.
- **Stub output.** If this backend has no LLM provider configured, it does not fail the
  request — it returns one finding with `category: "stub"` and an explanation starting
  `[STUB OUTPUT]`, so the UI can be built and demoed against a real response shape before an
  OpenRouter key exists. Never render that finding as if it were a real result; check
  `category !== "stub"` or `engine.provider !== "stub-unconfigured"` if you need to tell them
  apart in the UI.

## Auth: login and session (Phase 2)

For Member 1: this is what replaces the placeholder localStorage session in
`frontend/lib/session.ts`.

- **`POST /api/auth/login`** — body `{"email", "password"}`. On success, `200` with
  `{"access_token", "token_type": "bearer", "user": {"id", "email", "display_name"}, "organisation": {"id", "name", "slug"}, "role"}`.
  On failure, `401` with the standard error shape below — **the same message** whether the
  email is unknown, the password is wrong, or the account has no active membership in any
  organisation. Don't branch UI copy on the message text; there's deliberately nothing to
  distinguish.
- **Session.** Store `access_token` and send it as `Authorization: Bearer <token>` on every
  request to a protected route. There is no refresh token yet — a token lasts
  `AUTH_TOKEN_TTL_MINUTES` (12 hours by default); the client should send the user back to login
  on a `401`, not try to silently refresh.
- **`GET /api/auth/me`** — same bearer header, returns `{"user", "organisation", "role"}` (no
  `access_token` field). Use it to restore a session on page load instead of trusting a stored
  copy of `user`/`role`, since a membership can be deactivated between requests.
- **One token = one organisation.** A token is scoped to a single organisation at login time. A
  user who belongs to more than one organisation is logged into whichever membership was
  created first — there is no organisation switcher yet. Flag if any real account needs
  multi-organisation switching before this becomes a problem.

**Error codes the frontend should branch on:**

| HTTP status | `error.code` | Meaning |
|---|---|---|
| 401 | `UNAUTHENTICATED` | No token, an invalid/expired token, or a membership that is no longer active. Send the user to login. |
| 403 | `FORBIDDEN` | Not raised for an active account in individual-user mode (roles no longer gate anything); kept in the table because the code still exists. |
| 404 | `NOT_FOUND` | The resource doesn't exist, or it belongs to another account — these are indistinguishable on purpose (same code, same message). |
| 404 / 405 | `NOT_FOUND` | Also an unknown path (404) or a wrong method on a known path (405 keeps its status; there is no separate code). |
| 409 | `CONFLICT` | A guard refused the action (stale version, unfinished review, ...), or an `Idempotency-Key` clash. The message is user-readable. |
| 422 | `VALIDATION_ERROR` | The request body/params failed validation. `message` lists field locations only, never the submitted value. Also a NUL (`\u0000`) character in any text field, or an `Idempotency-Key` that isn't 1-200 visible ASCII characters. |
| 429 | `RATE_LIMITED` | Too many submissions; `retry_after` (seconds) and a `Retry-After` header say when to try again. |
| 500 | `INTERNAL_ERROR` | Never carries internals. `request_id` (also the `X-Request-ID` header) ties it to the server log. |

## Example responses

- [`examples/login_success.json`](examples/login_success.json) — `POST /api/auth/login`.
- [`examples/review_success.json`](examples/review_success.json) — `GET /api/reviews/{id}`, one
  `supported`, one `contradicted` finding (with evidence and a suggested correction), one
  `unverified` finding (no evidence).
- [`examples/review_error.json`](examples/review_error.json) — the safe error shape every
  endpoint uses on failure: `{"error": {"code", "message", "request_id"}}`. No stack traces, no
  raw provider errors, no internals (`services/api/src/inkloom_api/errors.py`).

## Open decisions

Recorded here rather than settled without the team, same spirit as Member 2's
`CONTRACTS.md` "Open integration questions".

**Answers proposed to Member 2's questions 6-8 (`services/verification/CONTRACTS.md`):**

6. **Tenant ID.** From the authenticated context (session/token), never trusted from the request
   body. If a future request body also carries a `tenant_id`, the API rejects a mismatch.
7. **Validation error handler.** This backend owns it (`services/api/src/inkloom_api/errors.py`):
   FastAPI's default 422 is replaced with one that reports only field locations, never the
   submitted value.
8. **Request/report IDs.** This backend generates `request_id` before calling the engine and
   persists the resulting report (`reviews` table), so it can be looked up later via
   `GET /api/reviews/{id}` without re-running the engine.

**Still open, need Member 1 and/or 2's input:**

1. **Offset units for the UI.** Confirmed as Unicode code points above (matching the engine) —
   Member 1, please confirm your highlighting code will convert rather than index `text` directly.
2. **Verdict → `verification_status` mapping.** The engine has no `conflicting_sources` or
   `not_applicable` verdict (`CONTRACTS.md` lists `SUPPORTED | CONTRADICTED |
   NOT_ENOUGH_EVIDENCE | ERROR`). This backend's mapping (Phase 3): `SUPPORTED → supported`,
   `CONTRADICTED → contradicted`, `NOT_ENOUGH_EVIDENCE → unverified`, `ERROR → unverified` (never
   surfaced as `contradicted`). `conflicting_sources` is reserved for when retrieval returns
   passages that themselves disagree — a backend-level judgement, not an engine verdict. Flag if
   this doesn't match what the review-queue UI expects to render.
