# Phase 4: Evidence validation and source management

Read `00_CONTEXT.md` first. Requires Phase 3.

## Goal
The backend never trusts the engine. Every finding's evidence is re-checked against approved sources for the correct brand.

## Routes delivered
- `GET /api/brands/{id}/sources`
- `POST /api/brands/{id}/sources`

## Tasks
1. Implement an evidence validator that runs on every engine response before anything is saved as valid. Reject and log an integrity error when:
   - a source ID is not in the retrieved, authorised set;
   - the source belongs to another brand or organisation, or is not approved for this review;
   - the quote is not present in the source text (normalise whitespace before the substring check);
   - the output fails the schema.
2. On rejection, set the review to `failed` or `needs_human_review` with a safe error code. Never save invalid evidence as valid.
3. Source registration: `POST /api/brands/{id}/sources` with role checks, file size and type validation, files stored outside public paths, status `draft` until approved, `sensitivity` field (normal or confidential).
4. Source listing with version and status, tenant scoped.
5. Source approval action with an audit event.
6. Preserve the source version used by each review (store `source_version_id` on evidence).

## Wiring with teammates
- Member 1: the Brand Knowledge screen needs name, type, version, status, last updated, sensitivity. Confirm fields.
- Member 2: their retrieval must read only approved sources for the right brand through the shared data layer. Confirm how.

## Tests (write now)
- Unknown source ID is rejected.
- Wrong-brand and cross-tenant source IDs are rejected.
- Quote not in the passage is rejected.
- Valid quote with extra whitespace is accepted.
- Draft source is never used as evidence.

## Done when
All five tests pass and an invalid engine response can never be saved as a valid result.

## Paste into Claude Code
> Read 00_CONTEXT.md and this file. Implement the evidence validator first with tests, then source management. Show me after each.
