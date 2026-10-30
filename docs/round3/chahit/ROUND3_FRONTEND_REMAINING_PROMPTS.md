# Round 3 frontend: remaining work, phase by phase

Replaces the build order in `ROUND3_FRONTEND_PROMPTS.md`. That older plan says governance is waiting on Darsh and that the product is single-user. Neither is true any more. Field names below come from `docs/governance.md` section 9, `contract/examples/governance_*.json` and `services/api/src/inkloom_api/schemas.py`.

## How to use this file

1. Run the phases in order. Each phase is one branch and one PR into `main`.
2. Start a new Claude Code session for each phase and paste only that phase's prompt. Each prompt tells Claude Code to read section 2 of this file first.
3. Do not start the next phase until the current one meets its "Done when" line.
4. Keep this file in place. Commit it on the Phase 0 branch so later branches have it.

## 1. Phase map

| Phase | What it delivers | New pages | Branch |
|---|---|---|---|
| 0 | Sync, baseline screenshots, contract map | | `r3/00-baseline` |
| 1 | Shared types, API calls, badges and states | | `r3/01-foundation` |
| 2 | Review page: summary strip, states, finding cards | | `r3/02-review` |
| 3 | Governance on Decide and Queue | | `r3/03-governance` |
| 4 | Audit trail on Record, workspace audit log | `/app/audit` | `r3/04-audit` |
| 5 | Team members and invitations | `/app/team` | `r3/05-team` |
| 6 | Accept invitation, workspace switcher | `/invite/accept` | `r3/06-invite-switch` |
| 7 | Trust Scorecard finish | | `r3/07-scorecard` |
| 8 | Brand voice findings, shown only when the API sends them | | `r3/08-tone` |
| 9 | Theme, responsive, accessibility and motion pass | | `r3/09-polish` |
| 10 | End-to-end tests | | `r3/10-e2e` |
| 11 | Demo script and docs | | `r3/11-demo` |

If time runs short, the minimum credible demo is Phases 0, 1, 2, 3, 7 and 10. Do Phases 5 and 6 next, because a team demo needs them.

### Backend gap: real tone checks

There is no tone or brand-voice checker on `origin/main` as of 2026-10-30 (`DECISIONS_PENDING.md` P5, `docs/round3/handoff-tone.md`). The API's `summary_counts.tone` only counts two style rules, `all_caps_run` and `emoji_run`. No finding has `check_type: "tone"`, `guideline_quote` or `validation_status`. Phase 8 builds the UI so it works when those fields arrive, and until then it shows nothing extra. The landing page keeps saying tone is "Coming next".

## 2. Guardrails (every phase must follow these)

### Scope

- Work only inside `audit-ai-final/frontend`. If the backend or contract seems wrong, stop and write a note for the owner. Do not edit it.
- Do not push to `main`. Work on the branch named in the prompt, with small, clear commits.
- Ask before adding a dependency or changing the order of page sections.
- Read before coding: `audit-ai-final/CLAUDE.md`, `audit-ai-final/frontend/AGENTS.md`, `audit-ai-final/design/DESIGN.md`, `audit-ai-final/design/tokens.css`, `docs/governance.md` section 9. This is a newer Next.js, so read the relevant guide in `node_modules/next/dist/docs/` before using any Next API.

### Theme: every screen must look like the same product

The look is "pressed paper". Light comes from the top-left. Raised means approved or available, pressed means contradicted or input, the dark die-cut window means evidence, and dashed means unverified.

1. **Tokens only.** Colours, fonts, radii, shadows, durations and easings come from `design/tokens.css`. No hard-coded hex values, no new fonts, and no new hues beyond the existing evidence-status colours.
2. **Reuse before creating.** Use these first:
   - Page structure: `StageHead`, `Panel`, `Panels`, `Option` from `components/app/Stage.tsx`
   - Primitives: `Button`, `Card`, `Heading`, `Field`, `PasswordField`, `Disclosure`, `SpecTable`, `TextLink`
   - Shared pieces: `Badges`, `States`, `Metrics`, `ConfirmDialog`, `BrandBar`, `AdditionsFrame` from `components/additions`
   - Existing classes: `add-*`, `add-badge`, `add-state`, `app-alert`, `tally`, `rows__item`, `evidence__quote`
3. **Typography and shape.** Gabarito 700 uppercase for headings, Instrument Sans for body text, radius 6px, no pills.
4. **New pages copy an existing page's structure.** Inside the workspace, follow `/app/queue`: `page.tsx` renders one client component, `layout.tsx` wraps it in `AdditionsFrame` and sets metadata as "Page name — Audit AI", and the content is `StageHead` plus numbered `Panel`s. Outside the workspace, follow `/login`: `main.auth` with the wordmark.
5. **CSS.** New styles go in `styles/additions.css`, using the same naming. Do not edit `base.css`, `primitives.css` or landing page styles. `additions.css` only loads where it is imported or under `AdditionsFrame`, so any page using a new `add-*` class must load it. `ReviewResult.tsx` and `RecordPanel.tsx` do not import it directly today, so check this on those pages.
6. **Motion.** 220ms buttons, 250ms links, 500ms reveals, with easing tokens and no bounce or spring. Reuse `app-sink`, `app-shift`, `app-deal` and `Reveal`. Every animation needs a `prefers-reduced-motion` fallback.
7. **Status.** Never by colour alone: always glyph, word and relief, as in `Badges.tsx`. "Unverified" is never worded as "false".
8. **Copy.** Plain language for brand managers, in the voice of the existing pages. Exact feature names: Source Watch, Trust Scorecard, Intent-lock, Data Passport, Evidence coverage. Original copy only.

**Visual check, required after any visual change.** `design/reference/` does not exist in this repo, so the reference is the working app. Screenshot with Playwright at 1182x937 and 390x844 and compare against `.round3-baseline/` and against `/app/queue` and `/app/review`. Check shadows, grain, radius, heading style, panel tabs, button look and spacing. Fix any drift before reporting done, and list the screenshot paths in your report.

### Data and behaviour

9. **Never invent data.** Every finding, count, metric, reviewer or risk level comes from the API. Fixtures live only in test files. A missing value shows an honest absent state, never 0 and never a guess.
10. **The backend decides.** Show a control only if its action is in `allowed_actions`, and still handle 401, 403, 409, 422 and 429. Show the API's message and request id, keep what the user typed, and re-fetch after every success so the status shown is the server's.
11. **`allowed_actions` missing vs empty.** Missing means an older backend, so keep today's behaviour. `[]` means nothing is allowed. Stored idempotency replays can return `[]` by default, so re-fetch the review with `GET /api/reviews/{id}` after any create, upload or re-run before drawing action controls.
12. **Types.** Every new field is optional in `lib/api/types.ts`, using the existing `Open<...>` pattern. Unknown values must not crash a screen.
13. **Humans decide.** Never auto-apply a suggestion.
14. **Solo users must not be worse off.** Personal workspaces (`workspace.is_personal: true`) must work as they do today, with no team-only clutter.
15. **Accessibility.** TypeScript strict, keyboard accessible, visible focus rings, `role="status"` for loading and empty, `role="alert"` for errors, 44px touch targets on mobile, no horizontal scroll at 390px.

### Before saying done

Run `npx tsc --noEmit`, `npm run lint`, `npm run build` and each relevant `node --experimental-strip-types qa/unit/<name>.test.mts`. Report the real output. Do not claim something works unless you ran it. Name anything you could not verify.

---

## Phase 0: Sync and baseline

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 0. Branch: r3/00-baseline. Change no product code.

1. Pull the latest main before branching. Local main may be behind origin/main.
2. Run the backend per services/api/README.md with scripts/seed.py --reset, then run the frontend.
3. Write audit-ai-final/frontend/ROUND3_BASELINE.md: each of the 15 routes, its files, its API calls, and whether it works now with seed data. Mark anything broken.
4. Save Playwright screenshots of every route at 1182x937 and 390x844 to audit-ai-final/frontend/.round3-baseline/ and add that folder to .gitignore.
5. Write audit-ai-final/frontend/ROUND3_CONTRACTS.md. For each field in docs/governance.md section 9 and each EvaluationOut field, record: sent by the API today (check schemas.py), typed in lib/api/types.ts yes/no, shown in the UI yes/no. List tone fields as NOT SENT.
6. Record tsc, lint, build and unit test results in the baseline file.
7. Commit the two docs and docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md.

Report: a table of routes (works/broken), and any place where the API differs from docs/governance.md.
```

**Done when:** both docs exist, screenshots are saved, and the build result is recorded.

---

## Phase 1: Shared foundation

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 1. Branch: r3/01-foundation. Read ROUND3_CONTRACTS.md. Add building blocks only: no page changes in this phase.

1. Types in lib/api/types.ts, all optional: on ReviewOut add workspace {id,name,is_personal}, author, owner, assigned_reviewer ({id,display_name} or null), workflow_status, risk_level, routing_reason {code,text,triggered_by[]}, approval_mode, allowed_actions, summary_counts {supported,contradicted,unverified,conflicting,tone,needs_human_review}, is_current_version. On FindingOut add review_reasons if it is missing. Widen required_reviewer_role to allow "reviewer" and "approver". Add types for AuditEventOut, AuditHistoryOut, WorkspaceAuditOut, MemberOut, MembersOut, InvitationOut, InvitationCreatedOut, InvitationsOut, WorkspaceMembershipOut, WorkflowActionOut.

2. API calls in lib/additions/ (same style as lib/additions/content.ts, using the existing client):
- POST /api/content/{id}/submit {content_version_id}
- POST /api/content/{id}/assign {reviewer_user_id or null}
- POST /api/content/{id}/mark-reviewed {content_version_id, note?}
- POST /api/content-versions/{id}/publish
- GET /api/content/{id}/audit?limit&cursor
- GET /api/workspace/audit?limit&cursor
- GET /api/workspace/members, PATCH /api/workspace/members/{user_id} {role}, DELETE /api/workspace/members/{user_id}
- GET and POST /api/workspace/invitations {email, role}, POST /api/workspace/invitations/{id}/revoke
- POST /api/invitations/accept {token}
- GET /api/workspaces, POST /api/auth/switch-workspace {workspace_id}
Confirm each path and body against services/api/src/inkloom_api/routers/ before writing it.

3. Badges in components/additions/Badges.tsx, same look as StatusBadge:
- WorkflowBadge: draft, submitted, in_review, needs_changes, reviewed, approved, rejected, published, blocked. Unknown values show "In progress" (docs/governance.md 9.1).
- RiskBadge: high, medium, low, clean; null shows "Not assessed yet". Glyphs must match RISK_LOOK in app/app/queue/Queue.tsx.
- RoleBadge: owner, approver, reviewer, writer; unknown values shown as-is.
- InvitationBadge: pending, accepted, revoked, expired.
- Keep the existing SeverityBadge.

4. States in components/additions/States.tsx, additive only:
- PartialState: says what is missing, what is still shown, and offers Retry. Classes add-state add-state--partial.
- NotProvided: a calm muted inline "Not provided" with optional custom wording.

5. components/additions/ApiActionError.tsx: inline alert for a failed action. Shows ApiError's message and request id and has plain wording for each code in contract/examples/governance_errors.json. Unknown codes fall back to the API message.

6. Unit tests in qa/unit/ in the existing style: unknown workflow status, null risk, unknown role, parsing of each new response using contract/examples/governance_*.json as fixtures.

Show the new badges and states on a temporary local page for the visual check, then delete that page. Do not commit it.
```

**Done when:** everything builds, tests pass, no existing page has changed, and new badges look like existing ones in screenshots.

---

## Phase 2: Review page

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 2. Branch: r3/02-review. Files: app/app/review/ReviewResult.tsx, components/additions/.

A judge must be able to see what was flagged, why, the proof and the next action within seconds. First show me a checklist of what ReviewResult.tsx already does for sections A, B and C below. Then change only the gaps.

A. Summary strip: create components/additions/ReviewSummary.tsx.
- Read review.summary_counts: supported, contradicted, unverified, conflicting, needs_human_review. Do not count in the browser when the API sends it.
- If summary_counts is missing (older backend), show "–" for each number. Never show 0 for a missing value.
- Show tone only when it is above 0, labelled "Style rules (capitals, emoji)". It is not a real tone check, so do not call it brand voice.
- Dismissed findings are still counted by the API. Do not subtract them.
- Reuse the .tally look and its click-to-filter behaviour, and keep the existing Tally working. Decide whether ReviewSummary replaces Tally on screen or sits beside it, and tell me why, so the page does not show two sets of counts.
- Two columns at 390px, 44px tap targets, enters with app-deal, reduced-motion fallback.

B. States: every review state must look different and explain itself.
- queued, analysing: existing Thinking component
- failed: ErrorState with error_summary and Retry via the existing rerun call
- completed with no findings: EmptyState saying "No problems were flagged" and listing what was checked (rule_checks)
- report_status or rules_status incomplete, or error_summary alongside findings: PartialState above the findings
- rules_status not_applied: keep the existing message
- network error, 403, 404, 429, 5xx: ErrorState with the right wording

C. Finding cards: audit FindingDetail, Suggestion, HeatText and fill the gaps.
- Span: use lib/text/codepoints.ts (spans are Unicode code points). If original_text does not match the span, show "Span could not be located" and do not highlight the wrong words.
- Verdict and severity badges with glyph and word.
- Evidence: the die-cut window with source title and version and relation (supports, contradicts, context). For unverified claims, show "Not proven yet" and no evidence block.
- Explanation, with its label hidden when null.
- Correction: keep suggested_correction (evidence-backed) visibly separate from safer_wording ("Safer wording, not evidence-backed"). Respect withheld_by_intent_lock.
- Why a person must decide: show requires_human_review and review_reasons in plain words. Known values: contradicted, not_enough_evidence, error, weak_evidence, below_policy_strength, compound_under_cited. Unknown values shown with underscores replaced by spaces.
- Validation status: the API does not send this field. Do not infer it. Render a badge only if a validation_status field is present.
- Selecting a finding highlights and scrolls to its span, and the reverse. Arrow keys move between findings, Enter opens, Esc closes. Reduced-motion fallback.
- Keep dismiss, restore, comments and Intent-lock working exactly as they do now.

Controls: show comment and dismiss only when allowed_actions lists comment and dismiss_finding (guardrail 11), and show re-run only when it lists rerun.

Tests: missing vs zero counts, code-point spans with emoji and accented text, mismatched span, unknown severity and unknown verdict, unverified shows no evidence block.
```

**Done when:** you can force every state in section B, a full finding shows all its parts without scrolling around, and a normal review looks the same as the baseline plus the strip.

---

## Phase 3: Governance on Decide and Queue

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 3. Branch: r3/03-governance. Read docs/governance.md 9.1, 9.2 and 9.5 and the three contract/examples/governance_review_item_*.json files. Files: app/app/decide/DecidePanel.tsx, app/app/queue/Queue.tsx, lib/additions/queue.ts, components/app/roles.ts.

1. components/additions/GovernanceBar.tsx: a compact definition list on the Decide page showing Author, Owner, Assigned reviewer ("Not assigned" when null), Workflow status (WorkflowBadge), Risk (RiskBadge), and "Why this needs review" from routing_reason.text. Stacked at 390px.
- In a personal workspace show only status, risk and reason.
- approval_mode "self" shows the plain line "Solo sign-off: you are the only member". Confirm the wording fits the personal example file.

2. Actions in DecidePanel: draw controls from allowed_actions.
- submit and resubmit: POST submit
- assign: reviewer picker filled from GET /api/workspace/members. Use the API's display names and allow unassign.
- mark_reviewed: with optional note, max 2000 characters
- request_changes, approve, reject: existing calls and ConfirmDialog
- publish: POST publish, with ConfirmDialog
- If allowed_actions is missing, keep today's buttons (guardrail 11).
- If is_current_version is false, say a newer version exists and link to it. The API already leaves approve out.
- Use the existing Button, Option and ConfirmDialog look. Do not add a new button style.

3. Errors: use ApiActionError. These must all read clearly: SELF_APPROVAL_FORBIDDEN, SELF_REVIEW_FORBIDDEN, SAME_REVIEWER_APPROVER_FORBIDDEN, REVIEW_REQUIRED, INVALID_TRANSITION, CONFLICT, FORBIDDEN. Keep the typed note. Re-fetch the review after every success and use the server's status.

4. Queue:
- Add the workflow status column.
- Use risk_level from the API when sent. lib/additions/queue.ts currently works out risk in the browser, so keep that only as a fallback for reviews with no risk_level and label it the same as today.
- Add assigned reviewer in team workspaces only.
- Filter by workflow status, using existing patterns.
- Keep existing empty and error states.

5. roles.ts returns true for everything. Do not use it to decide new controls. Leave its existing callers alone unless they conflict with allowed_actions, and tell me about any conflict.

Tests: all fields present (team approver example), writer example has no approve, personal example, unknown status, 403 on approve shows the API's message, status re-fetched after an action.
```

**Done when:** the three example roles each see the right controls, a personal workspace still works as today, and screenshots match the Queue and Review look.

---

## Phase 4: Audit trail and audit log page

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 4. Branch: r3/04-audit. Read docs/governance.md 9.3 and contract/examples/governance_audit_history.json.

1. components/additions/AuditTimeline.tsx: shared timeline. Each row shows actor display_name (null actor shows "System"), action in plain words, note, version number, and time formatted for the locale with the raw ISO in a title attribute. Add one glyph and word per action.
- Item actions: draft_created, version_created, recheck_requested, approval_granted, approval_rejected, changes_requested, source_changed, finding_dismissed, finding_restored, finding_commented, draft_submitted, routing_decision, review_requested, reviewer_assigned, reviewed, approval_denied, published.
- Workspace actions: account.registered, invite_created, invite_accepted, invite_revoked, member_role_changed, member_removed.
- Unknown actions show their name with separators replaced by spaces.
- Show before and after workflow status from details when present, as two WorkflowBadges. Do not print raw details JSON.
- "Load more" uses next_cursor. A 422 from a bad cursor shows ApiActionError.
- Use the existing list and row styling.

2. Record page: add the timeline to app/app/record/RecordPanel.tsx as a new Panel, reading GET /api/content/{id}/audit. Keep everything already on the page. Empty shows EmptyState, failure shows ErrorState with Retry. If content_item_id is missing, show NotProvided.

3. New page /app/audit: "Workspace audit log", built like /app/queue with AdditionsFrame, StageHead and Panel, reading GET /api/workspace/audit.
- Owners only on the server, so handle 403 with a calm "Only workspace owners can see this" state.
- Add it to the "More" list in components/layout/AccountNav.tsx only when session.role is "owner". The API stays the authority.

Tests: null actor, unknown action, pagination end, empty list, 403.
```

**Done when:** a draft's Record shows its full history, an owner can open `/app/audit`, a non-owner gets a clear message, and the page looks like `/app/queue`.

---

## Phase 5: Team page

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 5. Branch: r3/05-team. Read docs/governance.md 9.6, DECISIONS.md decision 2, and contract/examples/governance_members.json, governance_invitation_created.json and governance_invitations_list.json.

Build /app/team, structured like /app/queue: layout.tsx with AdditionsFrame and metadata "Team — Audit AI", page.tsx, Team.tsx. StageHead shows the workspace name. Add "Team" to the "More" list in AccountNav.

Panel 01, Members: rows from GET /api/workspace/members showing display_name, RoleBadge, joined date, and "You" when is_you.
- Change role and Remove appear only when the response's allowed_actions lists change_role and remove_member. Never offer them on your own row.
- Remove uses ConfirmDialog.

Panel 02, Invite someone: only when allowed_actions lists invite. Uses Field for email and the existing select look for role (approver, reviewer, writer, plus owner only if the backend accepts it; check the router and do not guess).

Panel 03, Invitation link: appears after creating an invitation.
- No email is sent by the backend, so the owner has to share the link. Say that plainly.
- Build the full link from window.location.origin + accept_path, with a Copy button that has a visible "Copied" state.
- The token is shown once and cannot be recovered. Say that too.
- Keep the token in memory only. Never put it in storage, logs or the page URL.
- Note that the link only works for the invited email, and show expires_at.

Panel 04, Invitations: rows from GET /api/workspace/invitations with email, InvitationBadge, invited by, expiry. Revoke on pending rows only, with ConfirmDialog.

Personal workspace: with only one member, show a short friendly explanation of what inviting does, and note that nothing changes for people who never invite anyone. Keep it calm and in the voice of existing pages.

Errors via ApiActionError: INVITE_ALREADY_PENDING, ALREADY_MEMBER, ROLE_ESCALATION_FORBIDDEN, SELF_ROLE_CHANGE_FORBIDDEN, LAST_OWNER_REQUIRED, FORBIDDEN. Keep typed input. Re-fetch after every success.

Tests: allowed_actions empty hides controls, token never written to storage, each error code, one-member state.
```

**Done when:** an owner can invite, copy the link, revoke, change a role and remove someone, a non-owner sees the list with no management controls, and the page passes the visual check.

---

## Phase 6: Accept invitation and workspace switcher

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 6. Branch: r3/06-invite-switch. Read contract/examples/governance_invite_accept.json and app/login/LoginForm.tsx.

A. Accept page at exactly /invite/accept?token=... because that is the accept_path the backend returns. Build it outside /app, styled like /login (main.auth with the wordmark), using useSearchParams inside Suspense the same way.

POST /api/invitations/accept requires a signed-in user, so:
- Signed out: explain the invitation and offer Sign in and Sign up. Both must return here afterwards. safeNext in LoginForm.tsx only accepts workspace paths, so extend it to also allow exactly the /invite/accept path. It must still refuse other sites and any other path. Add unit tests for this, including //evil.example and /invite/accept/../x. Also check that the sign-up form honours next.
- Signed in: show the signed-in email and an "Accept invitation" button. Do not accept automatically on page load.
- Success: the response is a full LoginResponse. Call signIn with it, using the same mapping LoginForm uses, then go to /app and show which workspace and role they joined.
- Errors with clear next steps: INVITE_EMAIL_MISMATCH (offer to sign out and use the invited email), INVITE_EXPIRED and INVITE_REVOKED (ask for a new one), INVITE_ALREADY_USED, NOT_FOUND, missing token.
- Never log the token or put it in storage. Passing it through next is acceptable.

B. Workspace switcher in AccountNav, shown only when GET /api/workspaces returns more than one.
- Lists workspace names and your role. The current one comes from is_current.
- POST /api/auth/switch-workspace, then signIn with the returned session.
- After switching, clear anything in the browser tied to the old workspace (selected brand, saved draft text, cached lists) and do a full navigation to /app. Search lib/ and components/ for localStorage and sessionStorage use and list what you clear. Data from one workspace must never appear in another.
- Same menu style as "More", keyboard accessible, and it works in the mobile menu too.
- 401 or 403 keeps the current workspace and shows the message.

Tests: safeNext cases, each invite error code, switcher hidden with one workspace, stored state cleared on switch.
```

**Done when:** a brand-new person can open an invite link, sign up, accept and land in the team workspace, and switching workspaces never shows the old workspace's data.

---

## Phase 7: Trust Scorecard finish

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 7. Branch: r3/07-scorecard. Read docs/round3/contracts.md sections 8, 10, 15, 16 and 17, and services/api/src/inkloom_api/routers/evaluations.py. Files: app/app/scorecard/, lib/additions/evaluationRun.ts. Extend only. Do not change how the Run button or the 409 flow works.

First list what is already shown. The API on main sends catch_rate, false_positive_rate, per_check, sample_size, run_at, id, status, engine_prompt_version, dataset_version, limits_note, latency_ms_p50, provider_failure_rate, coverage, by_split, provider_mode. Sections 15 to 17 of contracts.md are marked as draft proposals, so check whether any were built. Use only fields the API really sends, and treat anything else (headline, run, limitations, guard_regressions, headline numerators and denominators) as optional.

Then fill the gaps:
1. Missing vs zero: null, or a check with n = 0, shows "Not evaluated" with dashed relief, glyph and word. A real 0 shows "0%" with its denominator. Replace "–" for metric values on this page.
2. Show ratios as "37 of 40 (92.5%)" when numerator and denominator exist. With only a rate, show the rate and "Counts not supplied". Do not compute counts.
3. The headline caption "Sample: N labelled claims" is flagged as misleading in contracts.md section 8, because it isn't each metric's own denominator. Use the metric's own denominator when sent. Otherwise reword it so it does not imply one.
4. If the API sends a held-out headline, show that as the headline and label dev numbers "tuned on this data". If not, say plainly that the rates pool dev and held-out.
5. Run details in SpecTable: date with raw ISO in title, provider mode (scripted shown as "scripted answers, not a live model"), model, prompt version, dataset version, sample size, latency, provider failure rate, coverage. Missing shows NotProvided.
6. limits_note and coverage are always visible above the numbers, not in a disclosure.
7. Short "What is this?" explanations using Disclosure. Catch rate: of the claims that really were wrong, how many were flagged. False-positive rate: of the claims that were fine, how many were wrongly flagged. Sample size: how many labelled test items. Held-out: test items never used to tune the system. Check the wording against contracts.md section 15 before finalising.
8. No tone row unless the API sends one.
9. Numbers appear with app-deal, with no counting-up animation.

Tests: formatRate edge cases (0, null, 1, 0.0364), n = 0, by_split null, malformed response rejected, older run with missing optional fields. A search of the scorecard files must find no hard-coded percentages.
```

**Done when:** a stored run shows only API numbers with denominators where sent, and no run or a null value reads "Not evaluated".

---

## Phase 8: Brand voice findings

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 8. Branch: r3/08-tone. Read docs/round3/handoff-tone.md. Note that no tone checker exists yet and that the shape in that file is a DRAFT PROPOSAL. Check services/api/src/inkloom_api/schemas.py first. If the API now sends real tone findings, use the real field names and tell me what differs.

Nothing here may create or guess a tone finding. With today's API this phase must add nothing visible to any page.

1. Types, all optional: check_type "tone", guideline_source_id, guideline_source_title, guideline_source_version, guideline_quote, alternative_wording, validation_status.
2. lib/additions/tone.ts: one pure function that splits findings into shown and hidden, plus one constant TONE_UNCERTAIN_MODE = "omit". Show a tone finding only when guideline_quote is non-empty and validation_status is "validated". Everything else is hidden. Changing the constant to "uncertain" shows the failed ones as dashed "Uncertain" cards with no draft highlight.
3. Footnote when any are hidden: "N brand voice observations hidden because they cite no valid guideline passage". Do not show their content.
4. Card: extend FindingDetail. Same die-cut window as evidence, showing the guideline excerpt with document title and version, the highlighted span (code points), the explanation, and alternative_wording labelled as a suggestion. It is never auto-applied and goes only through the existing Editor flow. "Brand voice" badge with glyph and word, consistent with the rule badge but distinguishable.
5. Add "Brand voice" to the Tally and summary filters only when at least one shown tone finding exists. Keep the Phase 2 "Style rules" count separate.
6. Do not change the landing page's "Coming next" tone labels.

Tests use fixtures inside test files only: no passage is hidden and counted, a passage with validated status renders, each failed validation_status follows the constant, today's real API response shows no change on the page.
```

**Done when:** today's review page looks unchanged, and a test fixture with a guideline passage renders like part of the same product.

---

## Phase 9: Theme, responsive, accessibility and motion pass

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 9. Branch: r3/09-polish. Polish and verify only. No new features.

Pages: /app/review (every state), /app/decide, /app/queue, /app/record, /app/scorecard, /app/team, /app/audit, /invite/accept.

1. Theme consistency: screenshot each page at 1182x937, 768x1024 and 390x844, next to /app/queue and the baseline. For each page, fill in a table: tokens only, shadow direction, grain, 6px radius, heading style, StageHead and panel tabs, button look, spacing. Search the new code for hex colours, rgb(), inline font-family, new border-radius values, and raw durations, and fix every hit. Old pages must match the baseline apart from additions I asked for.
2. Responsive: no horizontal scroll, no clipped text, 44px tap targets, long quotes, emails and titles wrap, the evidence window scales.
3. Accessibility: run qa/axe-scan.mjs (axe-core is already installed, so no new dependency) on these pages and fix every serious or critical issue in new code. Check keyboard-only flow from review to decide, focus order, focus rings, aria-live for loading to loaded, role=alert for errors, and contrast of new badges with qa/contrast.mjs.
4. Motion: list every transition and animation added. Confirm it uses tokens, matches the timings, has a reduced-motion fallback, and causes no layout shift. Reserve space for the summary strip and skeletons.
5. Copy pass: plain language, no jargon, "Unverified" never worded as "false", same voice across all new pages.
6. Landing page text only, no layout or style changes: components/sections/Checks.tsx and Findings.tsx say some checks are "Coming next". Check which rules the engine really ships in services/verification and correct only labels that are now wrong. Tone stays "Coming next".
7. Record page: "Download as PDF · coming soon" stays as it is unless I say otherwise.

Deliver the consistency table, before/after screenshots and the axe summary.
```

**Done when:** no serious or critical axe issues in new code, no horizontal scroll at 390px, reduced motion verified, and the search for hard-coded styles comes back clean.

---

## Phase 10: End-to-end tests

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 10. Branch: r3/10-e2e. Put tests in audit-ai-final/frontend/e2e/ with one documented command and an e2e/README.md. Use the installed playwright package and node:assert in the same style as qa/*.mjs. Ask me before adding @playwright/test.

Run against the real backend with scripts/seed.py --reset and no live AI key. Do not mock the app's own API in journey tests. Passwords come from environment variables, as in qa/scorecard-run.mjs. Seed users are individual accounts, so team journeys create their team through real invitations in the test. Check whether signing in as several users in one run hits the auth rate limit, and handle that in setup, not by weakening the backend.

Journeys, one file each:
1. Upload to findings: log in, upload a text draft, run the check, see summary strip and a finding card with span, verdict and severity. A placeholder finding is clearly labelled when no provider is set.
2. Correction: safer wording is labelled as not evidence-backed, edit, save a new version, re-check, version number goes up, old approval no longer applies.
3. Solo decision: send back with a note, status and record update from the server, approve a fresh version, status updates. Acting on a stale version shows the 409 message.
4. Team workflow: owner invites writer, reviewer and approver through /app/team and /invite/accept. Writer submits, owner assigns, reviewer marks reviewed, approver approves, someone with permission publishes. At each step the visible controls match the API's allowed_actions.
5. Refusals: author sees no approve button, and a forced self-approval shows SELF_APPROVAL_FORBIDDEN wording, and the same for self-review.
6. Audit: the timeline on Record shows the workflow steps, /app/audit works for the owner, and a non-owner sees the refusal message.
7. Team management: revoke an invitation and the link fails with the right message, wrong email shows INVITE_EMAIL_MISMATCH, removing the last owner shows LAST_OWNER_REQUIRED.
8. Workspace switch: data from the first workspace does not appear after switching.
9. Dismiss, restore, comment, Intent-lock.
10. Scorecard: no run shows "Not evaluated", a stored run's numbers equal the API response exactly, no provider shows the 409 message.
11. Errors: block the API route for one test to see the network error and Retry recover, and an empty review shows its empty state.
12. Responsive smoke: no horizontal scroll at 390x844 on each page in Phase 9.
13. Tone: skip with the reason "API sends no tone findings" unless the backend now sends them. Never fake it.

Rules: assert on visible text and roles, not CSS classes; no arbitrary sleeps; screenshots on failure; tests clean up or use the seed reset.

Report the command, pass and fail counts, flaky tests, and what was skipped and why.
```

**Done when:** journeys 1 to 12 pass from a clean seed, and only journey 13 is skipped, with a stated reason.

---

## Phase 11: Demo and docs

```text
Read section 2 of docs/round3/chahit/ROUND3_FRONTEND_REMAINING_PROMPTS.md and follow it. This is Phase 11. Branch: r3/11-demo. No new features.

1. audit-ai-final/frontend/ROUND3_FRONTEND.md: what was added, which files, which API fields each screen reads, what the UI shows when a field is missing, and the test commands. List honestly what depends on backend work not shipped (real tone checks) and anything not verified live. Add the AI-assistance disclosure in the README's wording.
2. audit-ai-final/frontend/ROUND3_DEMO.md: a 5-minute script following one story: upload a draft, summary strip, a contradicted finding, a rule finding, the routing reason and risk, writer cannot approve, reviewer and approver act, status and audit trail update, Trust Scorecard with real numbers, date, config, limits and "Not evaluated". Mark which steps need a provider key and which work offline. Do not include a tone step unless it is live.
3. Run tsc, lint, build, unit tests and e2e, and search non-test UI code for hard-coded metrics, findings, reviewers or tone strings. Report real output.
4. Save final screenshots of each screen at 1182x937 and 390x844 to one folder for the submission.
```

**Done when:** a teammate can follow `ROUND3_DEMO.md` cold, and every claim in `ROUND3_FRONTEND.md` is backed by something that was run.

---

## Definition of done

- [ ] Uploads produce a summary from backend counts and complete finding cards
- [ ] Every review state explains itself, with Retry where it makes sense
- [ ] Author, owner, reviewer, status, risk, routing reason and history all show from the API
- [ ] Controls follow `allowed_actions`, and backend refusals are shown clearly
- [ ] Team, invite, accept, switch and audit pages work end to end
- [ ] Trust Scorecard is live, and "Not evaluated" is different from 0
- [ ] Tone findings appear only with a validated guideline passage, and nothing is faked
- [ ] Every new screen passes the theme checklist next to `/app/queue`
- [ ] Core end-to-end journeys pass
- [ ] No hard-coded metrics, findings, reviewers or colours in UI code
