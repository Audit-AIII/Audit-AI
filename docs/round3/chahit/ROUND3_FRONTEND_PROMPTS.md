# Round 3: Chahit (Frontend) — Work Plan + Phase-wise Claude Code Prompts

Project: Audit AI / InkLoom AI (team CodeNinjas). Your area: `audit-ai-final/frontend`. Nothing outside it changes.

Source of truth for the work: *Inkloom AI Round 3 — Individual Work Plan (Chahit Doshi)*. This file turns every line of that plan into phases, and each phase has one prompt you paste into Claude Code.

---

## 0. How to use this file

1. Run the phases **in order**. Each phase ends with a "Done when" check. Do not start the next phase until it passes.
2. At the start of **every** Claude Code session, paste the **Master guardrails** (section 2) first, then the phase prompt.
3. One phase = one branch = one small PR into `main` (branch protection is on). Commit often.
4. Phases 3, 4 and 5 depend on contracts from Krish and Darsh (section 3). Do Phase 1 and 2 while you wait for them.

## 1. What already exists vs what Round 3 asks for

I checked the current repo (`Audit-AIII/Audit-AI`, HEAD a104465). This tells you where to **extend** and where to **build new**. Do not rebuild what works.

| Round 3 requirement | What exists now | Gap you own |
|---|---|---|
| Review workspace: span, verdict, severity, evidence, explanation, correction, validation status | `app/app/review/ReviewResult.tsx` already shows findings, evidence quotes, suggestions, safer wording, rule findings, dismiss/restore, comments, Intent-lock | Summary counts are computed in the browser (`Tally`), the plan wants **backend-supplied counts**. No "validation status" field shown. No partial-result state. Needs a tidy audit of loading/empty/error/retry |
| Evidence-linked tone findings | Nothing. `check_type` is only `rule / retrieval / semantic`; there is no tone category in `lib/api/types.ts` | New: tone finding card, only rendered when it carries a guideline passage. Contract needed from Krish/Darsh |
| Trust Scorecard from live data | `app/app/scorecard/Scorecard.tsx` + `RunReport.tsx` + `lib/additions/evaluationRun.ts` already read `GET /api/evaluations/latest` and show catch rate, false-positive rate, per-check, sample size, dataset version, limits note | Missing/zero distinction audit, date and model/config display, metric explanations, "Not evaluated" state. Tone metrics when Krish adds them |
| Governance UI: author, reviewer, status, risk, allowed actions, routing reason, audit history | `queue/`, `decide/DecidePanel.tsx`, `record/RecordPanel.tsx` exist. `DECISIONS.md` says the product is **single-user**: roles gate nothing, routing is off | **Biggest risk.** The backend does not send reviewer / risk state / allowed actions today. Build the UI to render these **only when the API sends them**, and degrade cleanly when it does not. Do not invent them |
| Responsive loading / error / empty / partial states | `components/additions/States.tsx` has `EmptyState`, `LoadingState`, `ErrorState` | Add a `PartialState`, apply consistently on every Round 3 screen, check 390px |
| End-to-end tests of core journeys | Frontend has unit tests for parsing only | Add Playwright journeys: upload to findings to correction to decision to status |

**Honest note for the team:** two plan items (assigned reviewer, risk-based routing, tone findings) need backend fields that do not exist yet. The frontend work is real, but it can only be *demonstrated* when Darsh and Krish ship those fields. Phase 0 makes that dependency explicit so you are not blocked.

## 2. Master guardrails (paste at the start of every session)

```text
You are working ONLY inside audit-ai-final/frontend of this repo. I am Chahit, the frontend owner for Round 3 of the Inkloom AI hackathon.

READ FIRST, before any code:
- audit-ai-final/CLAUDE.md
- audit-ai-final/frontend/AGENTS.md  (this is a newer Next.js with breaking changes: read the relevant guide in node_modules/next/dist/docs/ before using any Next API)
- audit-ai-final/design/DESIGN.md  (Part A visual system, Part B product UI, sections 15-22)
- audit-ai-final/design/tokens.css  (the ONLY source of colours, fonts, radii, shadows, durations, easings)
- Look at the images in audit-ai-final/design/reference/screenshots/ with the Read tool.
- DECISIONS.md at the repo root (single-user product decision) and services/api/API.md (backend contract).

HARD RULES (do not break any of them):
1. Do not touch anything outside audit-ai-final/frontend. No edits to services/, contract/, member3_backend/, workflows, DECISIONS.md or README.md. If a backend or contract change is needed, STOP and write it as a note for me to send to Darsh/Krish.
2. Do not rewrite or restyle any working page or component. Extend by adding new files or small additive edits. Existing flows (sources, draft, review, decide, record, queue, insights, coverage, rules, guidelines, scorecard, login, landing) must behave exactly as before.
3. Same look as every other page: "pressed paper". Warm cardboard canvas, light from the TOP-LEFT, raised = approved/available, pressed = contradicted/input, dark die-cut window = evidence, dashed = unverified. Gabarito 700 uppercase headings, Instrument Sans body, radius 6px, no pills.
4. Tokens only. Use the CSS variables from tokens.css (--canvas, --ink, --ink-2, --accent, --surface, --deep, --paper-hi, --ok, --warn, --bad, --shadow-raised, --shadow-press, --shadow-well, --shadow-window, --r-ui, --r-panel, --dur-base, --dur-link, --dur-mid, --ease-ui, --ease-enter, etc.). No hard-coded hex colours, no new fonts, no new hues beyond the existing evidence-status colours.
5. Reuse existing building blocks: components/primitives (Button, Card, Heading, Field, Disclosure, SpecTable, TextLink), components/additions (Badges, States, Metrics, ConfirmDialog, AdditionsFrame, BrandBar), the existing CSS classes in styles/app.css and styles/additions.css (add-badge, add-state, app-alert, tally, etc.). Put any new CSS in styles/additions.css (or a new file imported the same way) using the same naming style. Do not edit base.css, primitives.css or the landing-page style files.
6. Motion must match the existing system: 220ms buttons, 250ms links, 500ms reveals, ease tokens from tokens.css, no bounce, no spring. Reuse the existing keyframes (app-sink, app-shift, app-deal, thinking-*) and the Reveal pattern before inventing any new one. Every animation and transition needs a prefers-reduced-motion fallback (animation: none).
7. Never convey status by colour alone: always glyph + word + relief (like components/additions/Badges.tsx). "Unverified" is NEVER shown as "false". Humans decide: never auto-apply a suggestion.
8. Never invent data. No hard-coded findings, counts, metrics, reviewers, risk levels or tone findings in UI code. Everything shown comes from the API response. If a field is missing, show an honest absent state ("Not evaluated", "Not provided"), never 0, never a made-up value. Test fixtures may exist ONLY inside test files.
9. Treat backend authorization as authoritative. Show allowed actions from the API, but if the API returns 403/409/422, show its message clearly (ApiError.userMessage + request id), never swallow it.
10. Every new unknown API field is optional in lib/api/types.ts (use the existing Open<...> pattern and optional properties) so older backends do not crash a screen.
11. TypeScript strict, keyboard accessible, visible focus rings, correct ARIA roles (role="status" for loading/empty, role="alert" for errors), 44px minimum touch targets on mobile.
12. Ask me before adding any dependency or changing the order of sections. Do not run `next dev` agents' auto-generated AGENTS.md changes as part of your diff unless they are already tracked.
13. After ANY visual change: run the app, screenshot with Playwright at 1182x937 and 390x844, compare against the reference screenshots and against two existing pages (e.g. /app/review and /app/scorecard), and fix any visual drift before you say you are done.
14. Before finishing: run `npx tsc --noEmit`, `npm run lint`, `npm run build`, and the existing unit tests. Report real results. Do not claim something works unless you ran it.
15. Small, clear commits. Do not push to main. Work on the branch I name. Commit messages end with the standard Co-Authored-By trailer.

When something in the task conflicts with a rule above, the rule wins; tell me about the conflict instead of working around it.
```

## 3. Contracts to agree BEFORE building (send these to teammates now)

You cannot build Phases 3 to 5 against fields that do not exist. Send these two messages today and ask for a reply with example JSON. The frontend will be written against whatever they confirm.

**To Krish (engine / evaluation / tone)**

```text
Hi Krish. For Round 3 I need two contracts confirmed with real example JSON (one file each in contract/examples):
1. Tone finding: fields I need per finding: finding_id, check_type ("tone"), original_text, span {start,end} (code points), guideline_source_id, guideline_source_title, guideline_quote (exact passage violated), explanation, alternative_wording (optional), validation_status (validated | span_not_found | unsupported | downgraded), severity. Tell me: for downgraded or unsupported tone judgments, should I show them as "uncertain" or omit them?
2. Evaluation metrics: the final shape of GET /api/evaluations/latest including: catch_rate and false_positive_rate WITH numerator and denominator, sample_size, run_at, model/provider/config (provider_mode, model_id, prompt_version), dataset_version, held-out vs dev split, limits_note, and per-check rows including tone. What does the API return when no run exists yet?
Also: which verdict/category values can appear that are not in lib/api/types.ts today?
```

**To Darsh (API / governance)**

```text
Hi Darsh. DECISIONS.md says single-user. For Round 3's governance UI I need to know exactly what the API will send, as example JSON in contract/examples:
1. On a review / content item: author (id + display name), owner, assigned_reviewer (id + display name or null), workflow_status (which values exactly: submitted, in_review, needs_changes, approved, blocked, ...), risk_state / risk_level, routing_reason (text or code), required_reviewer_role.
2. allowed_actions[] on the item for the current user (e.g. approve, request_changes, reject, assign, resubmit).
3. Audit history: endpoint and shape (actor, action, note, version_number, created_at).
4. Summary counts for a review: supported, contradicted, unverified, conflicting, tone, needs_human_review, so I stop counting in the browser.
5. Error shape for forbidden/conflict on workflow actions (I use the existing {error:{code,message,request_id}}).
If any of these will NOT exist in single-user mode, tell me now so the UI shows an honest "not provided" state instead.
```

Paste the replies into `audit-ai-final/frontend/ROUND3_CONTRACTS.md` (Phase 0 creates it). The prompts below read that file.

## 4. Phase map

| Phase | Plan section | Depends on | Branch name |
|---|---|---|---|
| 0 | Inspect, preserve, contracts | nothing | `r3/00-audit-and-contracts` |
| 1 | Shared states + summary strip | Phase 0 | `r3/01-states-and-summary` |
| 2 | Review workspace: finding cards | Phase 0 | `r3/02-finding-cards` |
| 3 | Trust Scorecard live metrics | Krish metrics contract | `r3/03-scorecard-live` |
| 4 | Tone / brand voice findings | Krish tone contract | `r3/04-tone-findings` |
| 5 | Governance UI | Darsh governance contract | `r3/05-governance-ui` |
| 6 | Responsive + a11y + motion polish | Phases 1 to 5 | `r3/06-polish` |
| 7 | End-to-end tests | Phases 1 to 5 | `r3/07-e2e` |
| 8 | Demo readiness + docs | all | `r3/08-demo-ready` |

---

## Phase 0 — Inspect existing routes and preserve working flows

Plan reference: *Suggested order, step 1: inspect existing routes/components and preserve working flows; agree contracts.*

```text
[Paste the Master guardrails first.]

PHASE 0 of Round 3. Branch: r3/00-audit-and-contracts. This phase writes NO product code and changes NO behaviour. It produces a safety net and one new doc.

1. Run the frontend (npm ci if needed, copy .env.example to .env.local, start the backend per the root README with `scripts/seed.py --reset`, then `npm run dev`). Log in with the seeded demo user.
2. Walk every route under app/app/* and the landing page. For each, record in a new file audit-ai-final/frontend/ROUND3_BASELINE.md: route, file(s), what it does, which API calls it makes (read lib/api/client.ts and lib/additions/*), and whether it works now with seed data. Be factual: mark anything broken instead of hiding it.
3. Take baseline Playwright screenshots (1182x937 and 390x844) of every route into audit-ai-final/frontend/.round3-baseline/ (add that folder to .gitignore if the repo ignores screenshots). These are the "before" images; later phases must not change them except where I asked.
4. Write audit-ai-final/frontend/ROUND3_CONTRACTS.md with three sections: (a) Findings & summary counts, (b) Tone findings, (c) Metrics, (d) Governance. For each, list the fields the UI needs (copy them from the Round 3 plan below), whether they ALREADY exist in lib/api/types.ts / the real API (check services/api/src/inkloom_api/schemas.py and routers), and mark each field: EXISTS / MISSING / WAITING-ON-KRISH / WAITING-ON-DARSH. Leave a clearly marked empty "Confirmed example JSON" block for me to paste teammate replies into.
   Round 3 needs - findings: exact flagged span, verdict, risk/severity, evidence or guideline passage, explanation, suggested correction, validation status; summary counts (supported, contradicted, insufficient-evidence, tone, needing review) supplied by the backend. Tone: guideline passage, span, explanation, alternative wording, validation. Metrics: catch rate and false-positive rate with numerator/denominator, sample size, evaluation date, model/config, limitations, missing vs zero. Governance: author/owner, assigned reviewer, workflow status, risk state, allowed actions, routing reason, audit history.
5. Run tsc, lint, build and existing unit tests; record the results in ROUND3_BASELINE.md.
6. Do not modify any other file. Commit only the two new .md files.

Report: a table of routes (works / broken), the list of MISSING contract fields, and the exact JSON examples I still need from Krish and Darsh.
```

**Done when:** `ROUND3_BASELINE.md` and `ROUND3_CONTRACTS.md` exist, baseline screenshots are saved, build passes, and teammates have the two messages from section 3.

---

## Phase 1 — Shared states and the scannable summary

Plan reference: *1. Review workspace — scannable summary using backend counts; clear loading, empty, partial-result, error and retry states.*

```text
[Paste the Master guardrails first.]

PHASE 1. Branch: r3/01-states-and-summary. Read ROUND3_BASELINE.md and ROUND3_CONTRACTS.md first.

GOAL: (a) a consistent set of loading / empty / partial / error / retry states so a failed or incomplete analysis never looks like a successful blank screen; (b) a scannable summary strip that uses BACKEND-supplied counts.

TASKS
1. Extend components/additions/States.tsx ADDITIVELY (do not change existing exports' behaviour or markup used elsewhere): add PartialState for "analysis finished but incomplete" (e.g. review.report_status / rules_status = "incomplete", or error_summary present with some findings). It must say what is missing, what is still shown, and offer Retry (re-run via the existing api rerun call) using the same glyph + word + relief pattern as ErrorState. Same classes family (add-state add-state--partial) with styles in styles/additions.css using tokens only.
2. In app/app/review/ReviewResult.tsx, route every non-success review state through these components: queued/analysing -> existing Thinking component (reuse, do not restyle); failed -> ErrorState with the backend error_summary and a Retry that calls rerun; completed with ZERO findings -> an explicit EmptyState saying "No problems were flagged" plus what WAS checked (rule_checks) - never a blank panel; incomplete -> PartialState above the findings that exist. Network failure (ApiError.status 0), 403, 404, 429 and 5xx must each show the right wording via ErrorState.
3. Summary strip: create components/additions/ReviewSummary.tsx that renders counts for supported, contradicted, insufficient evidence (unverified), documents disagree (conflicting_sources), tone findings, and "needs a person" (requires_human_review). Take the numbers from a backend summary object if ROUND3_CONTRACTS.md says one exists (add the optional `summary` type to lib/api/types.ts). If the backend does not send counts yet, fall back to counting review.findings in one clearly-named helper in lib/additions/review.ts, and show a small honest note "Counted from this review's findings" - do not pretend the backend supplied them. Reuse the existing Tally look (styles around .tally in app.css) and its click-to-filter behaviour; keep the existing Tally working. Counts that are not provided show "–", never 0. Tone count only appears if tone findings can exist for this review.
4. Animation: reuse app-deal / app-shift for the strip entering, 220ms tokens for hover/press; add reduced-motion fallbacks.
5. Mobile 390px: the strip wraps to 2 columns, tap targets 44px, no horizontal scroll.
6. Unit tests (the existing style in the repo) for: the count helper, missing vs zero, unknown verdict values not crashing.

CONSTRAINTS: existing review page behaviour for a normal completed review with findings must look the same as the baseline screenshot except for the new summary strip. Do not hard-code any number.

DONE WHEN: every review state (queued, analysing, failed, incomplete, completed-empty, completed-with-findings, network error) has a distinct, honest screen; summary shows "–" for unknown; tsc, lint, build, tests pass; before/after screenshots at both viewports attached to my report.
```

**Done when:** you can force each state (stop the API, use a failed review, empty draft) and every screen explains itself with a Retry where it makes sense.

---

## Phase 2 — Review workspace: complete, evidence-linked finding cards

Plan reference: *1. For each finding show: exact flagged span, verdict, risk/severity, evidence/guideline passage, explanation, suggested correction, validation status.*

```text
[Paste the Master guardrails first.]

PHASE 2. Branch: r3/02-finding-cards. Read ROUND3_CONTRACTS.md. The finding card is the heart of the demo: a judge must see what was flagged, why, the proof, and the next action within seconds.

AUDIT FIRST: open app/app/review/ReviewResult.tsx (FindingDetail, Suggestion, HeatText, Tally, RuleChecks) and list which of the 7 required elements it already shows: flagged span (highlighted in the draft text), verdict, severity, evidence/guideline passage, explanation, suggested correction, validation status. Show me that checklist before changing anything.

THEN, for each element that is missing or weak, fix it ADDITIVELY inside the existing look:
1. Flagged span: the highlighted text in the draft must use the finding's span, which is in UNICODE CODE POINTS (see lib/text/codepoints.ts - use it, do not use UTF-16 slicing). If original_text does not match the text at the span, show a visible "Span could not be located" note on the card instead of highlighting the wrong words.
2. Verdict + severity: use the existing FindingBadge/StatusBadge plus a new SeverityBadge in components/additions/Badges.tsx (glyph + word, low/medium/high/critical, unknown values shown as-is). Never colour alone.
3. Evidence: the quote sits in the existing dark die-cut "window" treatment with the source title and version (EvidenceOut.source_title / source_version_number) and the relation (supports / contradicts / context) as glyph + word. Several quotes allowed. When a claim is "unverified" show the existing "Not proven yet" wording and NO evidence block (never a fake quote).
4. Explanation: plain language under a small label, from finding.explanation; hide the label if null.
5. Suggested correction: reuse the existing Suggestion component. Keep "safer wording, not evidence-backed" visibly separate from an evidence-backed correction. Respect withheld_by_intent_lock. Never auto-apply anything.
6. Validation status: add an optional `validation_status` (and `validation_note`) to FindingOut in lib/api/types.ts ONLY if ROUND3_CONTRACTS.md confirms the field name; render it as a small badge ("Quote verified", "Quote could not be verified", "Downgraded") with glyph + word. If the field is not provided, render nothing - do not infer one.
7. "Needs a person" indicator from requires_human_review and any review_reasons the API supplies (a text list, shown only if present).
8. Selecting a finding in the list scrolls/highlights the matching span in the draft and vice versa, with the existing app-sink motion and a reduced-motion fallback. Keyboard: arrow keys move between findings, Enter opens details, Esc closes; focus ring visible.
9. Keep dismiss/restore, comments and Intent-lock exactly as they work now.

TESTS: unit tests for code-point span location with emoji and accented text, mismatched span, missing optional fields, unknown severity. Component-level checks for "unverified shows no evidence block".

DONE WHEN: a finding with every field shows all 7 elements; a finding with missing fields degrades gracefully; screenshots at 1182x937 and 390x844 match the existing review page's visual language; no regressions on dismiss/comment/locks.
```

**Done when:** you can point at any finding and say "span, verdict, severity, proof, why, fix, validation" without scrolling around.

---

## Phase 3 — Trust Scorecard from live evaluation data

Plan reference: *3. Render catch rate and false-positive rate from Krish's evaluation data; sample size, counts/denominators, date, model/config, limitations; missing vs zero; concise metric explanations.*

```text
[Paste the Master guardrails first.]

PHASE 3. Branch: r3/03-scorecard-live. Wait for Krish's confirmed metrics JSON in ROUND3_CONTRACTS.md. The Scorecard already exists (app/app/scorecard/Scorecard.tsx, RunReport.tsx, lib/additions/evaluationRun.ts, GET /api/evaluations/latest). EXTEND it; do not rebuild it and do not change how the run button/409 "no AI provider" flow works.

AUDIT FIRST: list what Scorecard.tsx/RunReport.tsx already show versus the plan: catch rate, false-positive rate, numerator/denominator for each, sample size, evaluation date (run_at), model/provider/config (provider_mode, engine_prompt_version, dataset_version), limitations (limits_note, coverage), per-check rows, by_split (dev vs held-out), and the missing-vs-zero rule.

THEN:
1. Every headline number comes from the API. Ratio objects (numerator, denominator, value) from by_split or the new fields are shown as "37 of 40 (92.5%)". If only a rate is supplied, show the rate and say "Counts not supplied" - do not compute counts.
2. Missing vs zero: value null -> "Not evaluated" (glyph + word, dashed relief like "unverified"); a real 0 -> "0%" with its denominator. A check with n = 0 -> "Not evaluated". Never render a null as 0, never default a number. Extend lib/additions/evaluationRun.ts validation only for fields Krish confirmed; keep rejecting malformed responses with the existing visible error.
3. Metadata block (use the existing SpecTable primitive): evaluation date and time (formatted for the user's locale, with the raw ISO in a title attribute), provider mode (live / scripted / mixed - show scripted clearly as "scripted answers, not a live model"), model id if supplied, prompt version, dataset version, sample size, latency p50, provider failure rate. Fields not supplied show "Not provided".
4. Limitations: always show limits_note and the verifier-only coverage statement from the API in a visible app-alert note above the numbers, not hidden in a disclosure.
5. Metric explanations: concise inline definitions via the existing Disclosure primitive or a small "What is this?" toggle next to each metric: Catch rate = of the claims that really were wrong, how many the system flagged. False-positive rate = of the claims that were fine, how many it wrongly flagged. Sample size = how many labelled test items. Held-out = test items never used to tune the system. Keep wording simple, no jargon. Add a one-line "How to read this" for judges.
6. Tone metrics: if per_check contains a tone row, show it with the same row component; if not, show a "Tone: Not evaluated" row only when the contract says tone is in scope. Do not invent it.
7. Empty state (no run yet): EmptyState with what a run does and the run button; error and 409 states via ErrorState/existing handling; loading via LoadingState.
8. Motion: numbers appear with the existing reveal (app-deal), no counting-up animation that could imply values changing; reduced-motion fallback.
9. Tests: unit tests for formatRate edge cases (0, null, 1, 0.0364), missing vs zero rendering helper, malformed response rejected, by_split null.

DONE WHEN: with a real stored run the page shows only API-sourced numbers with denominators, date, config and limitations; with no run it says "Not evaluated"; a grep for hard-coded percentages in the scorecard files finds none.
```

---

## Phase 4 — Evidence-linked tone and brand voice

Plan reference: *2. Display a tone finding only when it includes the brand-guideline passage it violates; respect backend validation; do not invent tone findings.*

```text
[Paste the Master guardrails first.]

PHASE 4. Branch: r3/04-tone-findings. Needs Krish's tone contract in ROUND3_CONTRACTS.md. If it is still missing, build against the documented optional fields below and keep everything behind "only renders when the API sends it". Nothing in the frontend may generate or guess a tone finding.

TASKS
1. Types: in lib/api/types.ts add, as OPTIONAL and open-ended, a tone finding shape that matches the confirmed contract: check_type "tone" (add to CheckType via the Open pattern), guideline_quote, guideline_source_id, guideline_source_title, alternative_wording, validation_status. Keep every existing type working.
2. Render rule (the key rule of this phase): a tone finding is shown ONLY if it carries a non-empty guideline passage. A tone item without one is NOT rendered as a finding. Put the count of such omitted items into a quiet footnote "N tone observations hidden because they cite no guideline passage" so nothing is silently lost, but do not show their content.
3. Validation handling (follow the contract): if the span cannot be located in the draft, or validation_status is unsupported/span_not_found/downgraded, then either show it as a clearly labelled "Uncertain" card (dashed relief, glyph + word, no highlight in the draft, explanation of why it is uncertain) OR omit it, exactly as the contract says. Use one config constant for that decision so it is a one-line change.
4. Tone finding card (extend FindingDetail, same die-cut window as evidence): exact draft span highlighted (code points), the cited guideline excerpt in the evidence window with the guideline document title and version, a plain explanation of why the span violates it, and alternative wording labelled as a suggestion (never auto-applied; Accept goes through the existing Editor flow only). A "Tone" badge using glyph + word, visually consistent with the existing rule badge but distinguishable.
5. Summary strip and Scorecard: the tone count appears in ReviewSummary only when tone findings are possible; tone is listed in the Scorecard only if the metrics contract includes it.
6. Filters: add "Tone" to the existing Tally filter list, same behaviour.
7. Copy: use "brand voice" in user-facing wording; follow the "Original copy only" rule in CLAUDE.md.
8. Motion/mobile/a11y identical to Phase 2 cards.
9. Tests: tone finding without guideline passage is not rendered and increments the hidden footnote; with passage renders span + excerpt + explanation; unsupported/downgraded follows the config; no tone code path creates a finding from anything except the API data.

DONE WHEN: a tone finding with a passage looks like part of the same product; one without a passage never appears; a grep shows no tone strings or findings fabricated in UI code.
```

---

## Phase 5 — Governance UI

Plan reference: *4. Show author/owner, assigned reviewer, workflow status, risk state, allowed actions; role-aware actions with backend authority; workflow states; routing reason; audit history.*

```text
[Paste the Master guardrails first.]

PHASE 5. Branch: r3/05-governance-ui. Needs Darsh's governance contract in ROUND3_CONTRACTS.md. IMPORTANT CONTEXT: DECISIONS.md records a single-user product (roles gate nothing, routing off). The Round 3 plan asks for reviewer/risk/routing display, so build every element as "render when the API provides it, otherwise a calm 'Not provided' state". Do not change DECISIONS.md and do not fake multi-user data.

EXISTING: app/app/queue/Queue.tsx, app/app/decide/DecidePanel.tsx, app/app/record/RecordPanel.tsx, components/app/roles.ts, lib/additions/queue.ts, GET /api/content/{id}/history, approve / request-changes endpoints.

TASKS
1. Types: add OPTIONAL fields to lib/api/types.ts exactly as Darsh confirmed: author, owner, assigned_reviewer, workflow_status, risk_state, routing_reason, allowed_actions. Workflow status handled with the Open pattern for: submitted, in_review, needs_changes (and the existing changes_requested), approved, rejected, blocked, source_changed. Unknown values are shown as-is, never crash.
2. Create components/additions/GovernanceBar.tsx: a compact header on the Decide page and in each Queue row showing Author/owner, Assigned reviewer, Workflow status (badge: glyph + word), Risk state (badge, glyph + word), and "Why this needs review" from routing_reason. Every missing field shows "Not provided" in the muted style, never blank, never a guess. Use the SpecTable/definition-list look already used elsewhere.
3. Workflow status badge component in Badges.tsx with all states above, same visual language as StatusBadge/SourceStatusBadge.
4. Role-aware actions: in DecidePanel, show exactly the actions listed in allowed_actions when the API supplies the list; if it does not, keep today's behaviour unchanged. Actions the user may not take are shown disabled with a one-line reason from the API when given - never hidden silently, never enabled optimistically.
5. Backend is the authority: every action call goes through the existing client; on 401/403/409/422/429 show the API's message and request id with ErrorState/inline app-alert; keep the form state so nothing the user typed is lost; after any success re-fetch the item so the status shown is the server's, not a local guess. ConfirmDialog (existing) for reject/send-back with the note field.
6. Audit history: in RecordPanel show the timeline from the history endpoint: actor, action, note, version number, time (glyph + word per action). Empty history -> EmptyState. If the API provides richer events, render them; if not, show only what exists.
7. Queue: add workflow status and risk columns/chips only if the list endpoint provides them; sorting/filtering by status uses existing patterns; empty and error states from Phase 1.
8. Mobile: GovernanceBar collapses to a stacked list at 390px.
9. Tests: all-fields-present, all-fields-missing, unknown workflow status, allowed_actions limiting the buttons, 403 on approve showing the API message, stale-status refetch after action.

DONE WHEN: with fields present, a reviewer sees who owns it, who reviews it, status, risk, why it was routed and what they may do; with fields absent, the pages look exactly like today plus honest "Not provided" labels; permission errors are clear.
```

---

## Phase 6 — Responsive, accessibility and motion polish

Plan reference: *Deliverable: responsive loading/error/empty/partial states.*

```text
[Paste the Master guardrails first.]

PHASE 6. Branch: r3/06-polish. All Round 3 UI exists now. Polish and verify; do not add features.

1. Responsive audit with Playwright at 1182x937, 768x1024 and 390x844 on: /app/review (all states), /app/scorecard (run, no run, error), /app/decide, /app/queue, /app/record. No horizontal scroll, no clipped text, tap targets >= 44px, long quotes and long document titles wrap, the die-cut evidence window scales.
2. Accessibility: run @axe-core/playwright on those pages (the repo's earlier review used it; if it is not in package.json, ask me before adding). Fix every serious/critical issue only in the new code. Check keyboard-only flow for review -> decide, focus order, focus rings, aria-live announcements for loading -> loaded, role=alert for errors, colour-independent status (glyph + word), contrast of new badges against the token palette.
3. Motion consistency: list every transition/animation I added, confirm it uses tokens (--dur-*, --ease-*), matches existing timing (220ms buttons, 250ms links, 500ms reveals), has a prefers-reduced-motion fallback, and does not shift layout (no CLS from late-arriving content: reserve space for the summary strip and skeletons).
4. Visual consistency: place my new screens next to the baseline screenshots of old pages and check shadows (raised/pressed/well/window), grain, radii (6px), typography (Gabarito 700 uppercase headings, Instrument Sans body), and spacing against tokens. Fix drift in new code only.
5. Copy pass: plain language for non-technical brand managers, no jargon, "Unverified" never worded as "false".
6. Landing page: README notes components/sections/Checks.tsx still labels terminology and accessibility "Coming next" although they work. Update ONLY that text (and add tone as "Coming next" only if it is not shipped) - no layout or style changes.

Deliver a before/after screenshot set and the axe report summary.
DONE WHEN: zero serious/critical axe issues in new code, no horizontal scroll at 390px, reduced-motion verified, and old pages are pixel-identical to baseline.
```

---

## Phase 7 — End-to-end tests for core journeys

Plan reference: *Deliverable: end-to-end tests for core user journeys; definition of done: upload -> findings -> correction/review -> status update.*

```text
[Paste the Master guardrails first.]

PHASE 7. Branch: r3/07-e2e. Playwright is already used for screenshots here; check package.json and ask me before adding @playwright/test or any new dependency. Tests live in audit-ai-final/frontend/e2e/ and must be runnable with one documented command.

SETUP
- Tests run against the real backend started with the seeded database (scripts/seed.py --reset) in offline/scripted-provider or stub mode. No mocking of the app's own API in the journey tests; no live AI key required. Document the exact steps in e2e/README.md.
- A helper logs in via the seeded demo user (see the seed script output; never commit passwords other than the documented seed demo one).

JOURNEYS (each is one test file)
1. Upload to findings: log in, open a brand, upload a draft (txt), run the review, assert the summary strip appears with counts, at least one finding card shows span, verdict badge, severity and (for rule findings) the rule quote/suggestion. Assert the stub/placeholder finding is clearly labelled when no provider is configured.
2. Correction flow: open a finding with a suggestion, assert "safer wording" is labelled as not evidence-backed, edit in the editor, save a new version, re-check, assert the version number increments and the old approval does not apply.
3. Decision and status: send back with a note, assert the status badge and record/history update from the server; approve a fresh version, assert the status; assert the API error message is shown when an action is forbidden or conflicting (force a 409 by acting on a stale version).
4. Dismiss / restore / comment on a finding; Intent-lock saved and warned on removal.
5. Scorecard: with no run -> "Not evaluated" state; (if a run is stored in the seed) numbers equal the API response exactly (fetch /api/evaluations/latest in the test and compare), denominators present; with no provider the run button shows the 409 message, not a blank page.
6. Error and empty states: stop/blackhole the API route for one test to see the network-error screen and Retry recover; an empty review shows the explicit empty state.
7. Tone (only if the backend supports it in the seed/test environment): a tone finding with a guideline passage is shown; mark test.skip with a clear reason otherwise - never fake it.
8. Governance (same rule): fields present -> GovernanceBar shows them; absent -> "Not provided".
9. Responsive smoke: the review page at 390x844 has no horizontal scroll.

Rules: tests assert on visible text and roles (getByRole), not CSS classes; no arbitrary sleeps (wait for states); screenshots on failure; tests clean up what they create or use the seed reset.
Report: the command, pass/fail counts, flaky tests, and which journeys were skipped and why.
DONE WHEN: journeys 1, 2, 3, 4, 5, 6 and 9 pass locally from a clean seed; skipped tests are skipped only for a missing backend field and say so.
```

---

## Phase 8 — Demo readiness and documentation

Plan reference: *Done when uploads produce a useful structured result, tone findings are evidence-linked, metrics are live, permissions reflect backend responses, and core end-to-end tests pass. Use real data in the final demo.*

```text
[Paste the Master guardrails first.]

PHASE 8. Branch: r3/08-demo-ready. No new features.

1. Write audit-ai-final/frontend/ROUND3_FRONTEND.md (NOT the root README): what was added per plan section (1 workspace, 2 tone, 3 scorecard, 4 governance), which files, which API fields each screen reads, which fields are optional and what the UI shows when absent, and the test command. Be honest: list anything that depends on a teammate field that is not shipped yet, and anything not verified live.
2. Write a 5-minute demo script (ROUND3_DEMO.md) following one story: upload a draft -> summary strip -> open a contradicted finding (span, severity, evidence quote, explanation, correction) -> a rule finding -> a tone finding with its guideline passage (only if live) -> send back / approve and watch the status and history update -> Scorecard with real numbers, denominators, date, config, limitations and the "Not evaluated" distinction. Note which steps need a provider key and which work in offline mode.
3. Run the whole checklist: tsc, lint, build, unit tests, e2e, and a final grep proving no hard-coded metrics, findings, reviewers or tone strings in non-test UI code. Report the real output.
4. Final screenshots of each Round 3 screen at 1182x937 and 390x844 into a folder I can attach to the submission.
5. Add the AI-assistance disclosure line for Round 3 frontend work in ROUND3_FRONTEND.md (Claude Code, under Chahit's direction and review), matching the README wording.

DONE WHEN: a teammate can follow ROUND3_DEMO.md cold and every claim in ROUND3_FRONTEND.md is backed by something you ran.
```

---

## 5. Definition of done (from the plan, as a checklist)

- [ ] Uploads produce a useful structured result (summary + finding cards) — Phases 1, 2
- [ ] Every finding shows span, verdict, severity, evidence/guideline, explanation, correction, validation status — Phase 2
- [ ] Tone findings appear only with a guideline passage and respect backend validation — Phase 4
- [ ] Scorecard metrics are live, with denominators, date, config, limits; "Not evaluated" differs from 0 — Phase 3
- [ ] Governance shows owner, reviewer, status, risk, allowed actions, routing reason, history; backend errors shown — Phase 5
- [ ] Loading / empty / partial / error / retry states everywhere — Phases 1, 6
- [ ] Core end-to-end journeys pass — Phase 7
- [ ] No hard-coded metrics or findings anywhere in UI code — Phase 8 grep

## 6. If you get stuck

- **A teammate has not replied yet:** run Phases 1, 2 and 6 first; they depend on nothing.
- **Claude Code wants to edit backend or contract files:** say no, write the request as a note to Darsh or Krish.
- **A prompt makes the old pages look different:** compare with `.round3-baseline/` screenshots and ask Claude Code to revert the drift.
- **Time is short:** the minimum credible demo is Phases 0, 1, 2, 3 and 7. Tone and governance only count if the backend really sends the data.
