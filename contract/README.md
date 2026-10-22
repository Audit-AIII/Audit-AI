# INKLOOM AI shared contract (draft, v0.1.0)

Owned by Member 3 (backend). This is what Members 1 (frontend) and 2 (engine) read to avoid
guessing field names, status strings or role names. It describes the **backend's API layer** —
what `GET /api/reviews/{id}` and friends return to the frontend. It is a different, higher-level
vocabulary than Member 2's engine contract
([`services/verification/CONTRACTS.md`](../services/verification/CONTRACTS.md)): the backend
calls the engine in-process, then maps its `Verdict`/`ReportStatus` onto the status strings below
before anything reaches the frontend. The engine's contract is not re-exported to the frontend
directly.

**Status: draft, Phase 1.** Nothing here is final until Members 1 and 2 have reviewed it. Items
under [Open decisions](#open-decisions) are this member's proposal, not yet confirmed.

## Status strings

These come from `00_CONTEXT.md`'s shared contract values and are enforced as Postgres CHECK
constraints in [`services/api/src/inkloom_api/statuses.py`](../services/api/src/inkloom_api/statuses.py)
(the single source of truth — this file is generated from it, not hand-maintained separately).

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
`changes_requested`. See the governance invariants in `00_CONTEXT.md`.

**Missing evidence means `unverified`, never `false`.** A finding with no supporting or
contradicting evidence must use `verification_status = unverified`, not `contradicted`.

## Role names (confirmed, Phase 2)

One role per permission. The permission table lives in
[`services/api/src/inkloom_api/auth/permissions.py`](../services/api/src/inkloom_api/auth/permissions.py).

| Role | submit | manage_sources | review | approve | administer |
|---|---|---|---|---|---|
| `submitter` | yes | | | | |
| `source_manager` | | yes | | | |
| `reviewer` | | | yes | | |
| `approver` | | | yes | yes | |
| `admin` | yes | yes | yes | yes | yes |

The governance invariant `if role not allowed to approve ... deny` checks the `approve`
permission, which only `approver` and `admin` hold. `admin` holds every permission rather than
being a separate "can do nothing itself" role, so one person can run a brand-new organisation
alone during setup.

## Finding and Review schema

JSON Schema: [`schemas/finding.schema.json`](schemas/finding.schema.json),
[`schemas/review.schema.json`](schemas/review.schema.json). A `Review` embeds its `findings`;
each `Finding` embeds its `evidence`. These describe the response body of `GET /api/reviews/{id}`.

Field names match the backend's `findings`/`evidence_links` tables (`member3_backend/00_CONTEXT.md`
task 3) exactly: `finding_id`, `category`, `severity`, `original_text`, `span` (`{start, end}`,
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

## Example responses

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
