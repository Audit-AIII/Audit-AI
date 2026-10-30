# Round 3 frontend

What Round 3 added to the frontend, what each screen reads from the API, and what was and wasn't verified. Field details are in [ROUND3_CONTRACTS.md](ROUND3_CONTRACTS.md), the "before" state in [ROUND3_BASELINE.md](ROUND3_BASELINE.md), and theme and accessibility results in [ROUND3_POLISH.md](ROUND3_POLISH.md).

## What was added

| Area | What it does now | Main files |
|---|---|---|
| Review workspace | Server-counted summary. A distinct screen for checking, failed, partial, empty and load errors. Finding details with verdict, severity, source and version, relation and reasons for review. Keyboard use of the findings list | `app/app/review/ReviewResult.tsx`, `components/additions/ReviewSummary.tsx` |
| Governance | Status, risk, routing reason, author, owner and reviewer. Controls drawn from `allowed_actions`, including send for review, assign, mark as reviewed and mark as published | `components/additions/GovernanceBar.tsx`, `app/app/decide/DecidePanel.tsx`, `app/app/queue/Queue.tsx` |
| Audit | Draft history on Record, and a workspace log for owners | `components/additions/AuditTimeline.tsx`, `app/app/audit/` |
| Team | Members, role changes, removal, invitations with a one-time link | `app/app/team/` |
| Invitations and switching | Accept page for new and existing users, workspace switcher that forgets the old workspace's browser data | `app/invite/accept/`, `components/layout/AccountNav.tsx`, `lib/safeNext.ts` |
| Trust Scorecard | "Not evaluated" kept apart from 0%, counts with each split, plain definitions | `app/app/scorecard/RunReport.tsx`, `lib/additions/evaluationRun.ts` |
| Brand voice | Display rule and card, ready for when the API sends real findings | `lib/additions/tone.ts` |

New pages: `/app/team`, `/app/audit`, `/invite/accept`.

## What each screen reads

| Screen | API | Fields it depends on | If a field is missing |
|---|---|---|---|
| Review | `GET /api/reviews/{id}` | `summary_counts`, `findings`, `report_status`, `rules_status`, `allowed_actions` | A missing count shows "–". With no `allowed_actions`, today's controls stay |
| Decide | `GET /api/reviews/{id}`, `GET /api/workspace/members`, workflow routes | `workflow_status`, `risk_level`, `routing_reason`, `author`, `owner`, `assigned_reviewer`, `approval_mode`, `allowed_actions`, `is_current_version` | No `workflow_status`: no governance bar. A null reviewer shows "Not assigned". Null risk shows "Not assessed yet" |
| Queue | `GET /api/reviews`, `GET /api/workspace/members` | `risk_level`, `workflow_status`, `assigned_reviewer` | No `risk_level`: the browser's own earlier risk label is used |
| Record | `GET /api/reviews/{id}`, `GET /api/content/{id}/audit` | `items`, `next_cursor` | No item id: "Not provided" |
| Team | `GET /api/workspace/members`, `GET /api/workspace/invitations` | `members`, `allowed_actions` | Nothing is offered without the matching action |
| Audit log | `GET /api/workspace/audit` | `items`, `next_cursor` | A 403 shows "Only workspace owners can see this." |
| Scorecard | `GET /api/evaluations/latest` | See `ROUND3_CONTRACTS.md` | Null rate: "Not evaluated". Null detail: "Not provided". A wrong shape shows an error, never numbers |

## Depends on work not shipped

- **Real brand voice checks.** No tone checker exists (`DECISIONS_PENDING.md` P5, `docs/round3/handoff-tone.md`). The UI shows nothing extra today. Its field names follow a draft proposal, so they may need adjusting when a checker ships.
- **Held-out headline on the Scorecard.** The API's top-level rates pool every split and have no counts. The page says so, and uses a `headline` field if one is added (`docs/round3/contracts.md` section 17).
- **Validation status on claim findings.** The API doesn't send it, so no badge appears.

## Points for the backend owner

1. `workspace.is_personal` stays `true` after someone joins, so the UI goes by the member count.
2. In a solo workspace the routing text says "a reviewer must check". The UI drops that clause for someone alone in a workspace.
3. `/api/auth/me` has no `memberships_count`, though `docs/governance.md` section 10 lists it.

## Verified, and how

Results from 2026-10-30, against a local backend with no AI keys.

| Check | Command | Result |
|---|---|---|
| Types | `npx tsc --noEmit` | Pass |
| Lint | `npm run lint` | Pass, no warnings |
| Build | `npm run build` | Pass |
| Unit tests | `node --experimental-strip-types qa/unit/<name>.test.mts` | All 11 files pass |
| End-to-end, real backend | `npm run e2e` (setup in `e2e/README.md`) | 12 passed, 0 failed, 1 skipped (tone). Also passed on a repeat run without reseeding |
| Forced states in the browser | `qa/review-states.mjs`, `qa/decide-governance.mjs`, `qa/audit-trail.mjs`, `qa/team-page.mjs`, `qa/invite-flow.mjs`, `qa/scorecard-states.mjs`, `qa/tone-findings.mjs` | All pass |
| Solo regression | `qa/single-user-walk.mjs` | Pass |
| Accessibility and responsive | `qa/round3-polish.mjs` | 0 axe violations, no sideways scroll, on 14 states at 3 sizes |
| Drift from baseline | `qa/round3-drift.mjs` | Pages not meant to change differ by at most 0.99%, details in `ROUND3_POLISH.md` |

## Not verified

- **With a live AI provider.** All runs used the offline seed or a server with no keys, so real AI findings on a new draft weren't exercised, including real safer wording and suggested corrections.
- **A stored evaluation run from the real backend.** The Scorecard's run view was tested with the API's documented example, because running one needs a provider.
- **Screen readers.** Roles and labels are checked by axe and the tests, but no one has listened through it with a real screen reader.
- **Browsers other than Chromium.**
- **Deployment.** Everything ran locally.

## AI assistance

Round 3 frontend work was written with Claude Code (Anthropic) under Chahit's direction. It still needs Chahit's review before the README's disclosure line ("who reviewed and tested it") applies to this work.
