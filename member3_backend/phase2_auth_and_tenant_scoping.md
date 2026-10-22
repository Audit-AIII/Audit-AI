# Phase 2: Auth and tenant scoping

Read `00_CONTEXT.md` first. Requires Phase 1.

## Goal
Every protected request is authenticated, tied to an active membership, and scoped to one organisation.

## Tasks
1. Implement server-side authentication (choose a simple method that fits the stack; ask me if unsure). Never put secrets in the frontend.
2. Add an auth dependency that loads the user and their active membership and role, and rejects revoked or inactive memberships.
3. Define roles (for example: submitter, source manager, reviewer, approver, admin) and a permission table for: submit, manage sources, review, approve, administer. Confirm the names with me before coding.
4. Derive `organisation_id`, `user_id` and role from the authenticated membership only. Ignore any such value in request bodies or query strings.
5. Add a tenant-scoped query helper so every read and write filters by organisation, directly or through a verified parent.
6. Implement one protected route end to end (for example `GET /api/brands/{id}/sources`) to prove the pattern.
7. Add safe error responses: 401, 403, 404 without leaking whether another tenant's record exists.

## Wiring with teammates
Give Member 1 the exact login and session behaviour and the error shapes for 401 and 403 so their client handles them centrally.

## Tests (write now)
- Org A cannot read or mutate org B's records.
- Changing `organisation_id` in a body grants nothing.
- Revoked membership loses access.
- Guessed IDs return a safe 404 or 403.
- Role escalation attempts are denied.

## Done when
All five tests pass and the protected route works with a real login.

## Paste into Claude Code
> Read 00_CONTEXT.md and this file. Confirm role names with me first. Implement tasks 1 to 7 step by step, and write the tests as you go.
