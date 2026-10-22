# Phase 6: Versioning, approval and audit

Read `00_CONTEXT.md` first. Requires Phase 5.

## Goal
Humans approve an exact reviewed version, stale or unsafe approvals are blocked, and every important action is on the audit trail.

## Routes delivered
- `POST /api/content/{id}/versions`
- `POST /api/reviews/{id}/rerun`
- `POST /api/content-versions/{id}/approve`
- `POST /api/content-versions/{id}/request-changes`
- `GET /api/content/{id}/history`

## Tasks
1. New version: create an immutable version with the next number and canonical hash. Never overwrite a reviewed version. The old approval becomes historical only.
2. Rerun: start a review for an explicit version.
3. State machine: define allowed transitions between review states and reject invalid ones with a safe error.
4. Approve: allow only an authorised role. Block when analysis failed, evidence is invalid, the review is stale (`current_version_id != reviewed_version_id`), a cited source was superseded after the review ran, or risk policy requires a different approver. Store the exact `content_version_id` and hash.
5. Request changes and reject with comments.
6. Risk routing: high or critical findings, contradictions, conflicting sources and uncertain results go to `needs_human_review`; keep the rules deterministic and documented.
7. Audit events (append-only) for submit, source approval, review, edit, request changes, approve, reject and retries. Write the state change and its audit event in the same transaction where feasible.
8. History endpoint: versions, decisions, actors, timestamps, scoped to the organisation.

## Wiring with teammates
- Member 1: Review Queue and Audit History screens need exact fields (actor, timestamp, action, version, decision) and error codes for 401, 403, 409. Confirm the shapes.
- Member 1: the UI must show old approval as not applying to a new version. Provide a clear `is_current` or equivalent field.

## Tests (write now)
- Non-approver gets a safe 403 or 409 and an audit event where appropriate.
- Stale approval rejected.
- Approval blocked when analysis failed or evidence invalid.
- Edit after approval creates a new version that is not approved.
- Concurrent reviewer actions leave state and audit consistent.
- Invalid transitions rejected.

## Done when
Full flow works in the real UI: submit, request changes, edit to a new version, rerun, approve, open audit history.

## Paste into Claude Code
> Read 00_CONTEXT.md and this file. Write the state machine and its tests first, then approval, then audit and history. Show me after each.
