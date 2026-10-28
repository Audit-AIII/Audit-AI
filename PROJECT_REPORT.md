# Round 3 governance: project report

Backend team governance, permissions and risk-based routing for InkLoom AI (owner: Darsh).
Written 2026-10-28, at the end of an autonomous run through Phases 0–6. The full design, the
role x action matrix and the API shapes are in [`docs/governance.md`](docs/governance.md). Open
questions are in [`DECISIONS_PENDING.md`](DECISIONS_PENDING.md).

**Final state:**
- **Backend:** 420 tests pass, and ruff reports nothing new.
- **Verification engine:** 2004 tests pass (3 expected failures), run on the merged main.
- **Frontend:** lint is clean, the unit tests pass, the build succeeds, and all 15 pages load.
- **Live smoke test:** sign-up → brand document → check → approve passes over real HTTP.

## 1. What each phase delivered

| Phase | Commit | Delivered | Main files |
|---|---|---|---|
| 0. Inspect and plan | `4326865`, `9fd5108` | Inspection of the existing schema, endpoints and access checks; conflicts with contracts.md; decisions D1–D6 (all answered); contract examples for the frontend | `docs/governance.md`, `contract/examples/governance_*.json` |
| 1. Workspaces, members, invitations | `4461fea` | Every account keeps its personal workspace (the existing organisation) as `owner`. Owners invite people as owner / approver / reviewer / writer. Invitation tokens are random, stored only as a hash, single use, and expire after 7 days. Switch workspace; list, change and remove members; last-owner and no-self-promotion rules. New error codes are carried in the existing error body | migration `0014`, `workspace_service.py`, `routers/workspace.py`, `errors.py` (`ApiException`), `DECISIONS.md` (decision 2) |
| 2. Roles enforced server-side | `d20ffe6` | One role x action table and one `can()` helper used by every route. Writers edit, re-check and submit only their own drafts. Every review carries `allowed_actions` and `is_current_version`, built from the same rules the routes enforce | `auth/permissions.py`, `auth/dependencies.py`, `review_queries.py`, every router |
| 3. Author can't approve own content | `e269907` | 403 `SELF_APPROVAL_FORBIDDEN` for whoever wrote the draft or the version being approved, owners included, whenever someone else could approve. The refusal changes nothing and writes `approval_denied`. Solo sign-off (D1) is recorded as a self-approval. `approval_mode` on reviews | `approval_service.py`, `routers/content_versions.py` |
| 4. Risk-based routing and workflow | `47ce198` | `workflow_status` on every draft (draft → submitted / in_review → reviewed / needs_changes → approved → published, plus rejected and blocked). Krish's §19 mapping lives in one file, and unknown statuses and reason codes route as medium. Routes added: submit, assign, mark-reviewed, publish. `REVIEW_REQUIRED`, D4 implicit submit, D6 separation of duties, re-routing when findings change, blocked on a failed check or a changed source. Reviews now carry workspace, author, owner, assigned reviewer, risk level, routing reason and summary counts. The strict check on verification status was dropped (D3) | migration `0015`, `risk_policy.py`, `workflow_rules.py`, `workflow.py`, `schemas.py`, `contract/schemas/review.schema.json` |
| 5. Audit trail | `4f55ca8` | `GET /api/content/{id}/audit`: newest first, cursor-paginated, with stable action names (older event types mapped). `GET /api/workspace/audit` for membership events (owners only). A database trigger makes `audit_events` append-only | migration `0016`, `audit_history.py` |
| 6. Tests | `218ffef` | An end-to-end run with separate users. At every state, each person's `allowed_actions` is exact, and every action not listed is refused without changing anything. Also the solo flow, and the author unable to publish their own work | `tests/test_e2e_governance.py` |

New test files: `test_workspace_membership.py`, `test_permissions.py` (rewritten),
`test_governance_roles.py`, `test_self_approval.py`, `test_risk_routing.py`,
`test_audit_trail.py`, `test_e2e_governance.py`.

## 2. Routes and their status

**Backend: 47 routes, all registered.** Every one except login, register and health needs a
token (`test_api_stability.py`). Every one has a response schema. Every route that names a
draft, version, finding, member or invitation answers 404 for another workspace's id.

| Area | Routes | Status |
|---|---|---|
| Auth | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/switch-workspace` (new) | ok |
| Workspaces (new) | `GET /api/workspaces`, `GET /api/workspace/members`, `PATCH` / `DELETE /api/workspace/members/{user_id}`, `POST` / `GET /api/workspace/invitations`, `POST /api/workspace/invitations/{id}/revoke`, `POST /api/invitations/accept`, `GET /api/workspace/audit` | ok, tested; **no frontend caller yet** |
| Brands and sources | `GET` / `POST /api/brands`, `GET` / `POST /api/brands/{id}/sources`, `.../approve`, `.../versions`, `.../withdraw`, `DELETE .../sources/{sid}`, `GET` / `PUT /api/brands/{id}/rules` | ok; writes now need approver or owner |
| Drafts and reviews | `POST /api/reviews`, `POST /api/reviews/upload`, `GET /api/reviews`, `GET /api/reviews/{id}`, `POST /api/reviews/{id}/rerun`, `POST /api/content/{id}/versions`, `GET /api/content/{id}/history` | ok |
| Workflow (new) | `POST /api/content/{id}/submit`, `.../assign`, `.../mark-reviewed`, `POST /api/content-versions/{id}/publish`, `GET /api/content/{id}/audit` | ok, tested; **no frontend caller yet** |
| Decisions | `POST /api/content-versions/{id}/approve`, `.../request-changes`, `GET` / `PUT .../locks` | ok; now governed |
| Findings | `POST /api/findings/{id}/dismiss`, `.../restore`, `GET` / `POST .../comments` | ok |
| Insights and Scorecard | `GET /api/analytics/brand-risk`, `GET /api/evaluations/latest`, `POST /api/evaluations` (owner only now) | ok |
| Health | `GET /health` | ok |

**Frontend: 15 pages, all returning 200** on the production build (`next start`):
`/`, `/login`, `/app`, `/app/coverage`, `/app/decide`, `/app/draft`, `/app/guidelines`,
`/app/insights`, `/app/queue`, `/app/record`, `/app/review`, `/app/review-edit`, `/app/rules`,
`/app/scorecard`, `/app/sources`. An unknown path correctly returns 404.
- **Every frontend API call has a backend route:** the 22 paths the frontend calls all exist.
- **Every internal link points to a page.**
- **No orphan pages.**

## 3. Errors found during verification and how each was fixed

| # | Found | Root cause | Fix |
|---|---|---|---|
| 1 | Smoke test failed on the analytics step (baseline, before any Round 3 change) | An additive `dismissed_finding_rate` field broke the smoke test's exact key-set check | The smoke test now checks that the required keys are present (`scripts/smoke_test.py`) |
| 2 | Smoke test failed after Phase 4 | It still asserted the single-user rule `required_reviewer_role == null` | It now checks for a Round 3 routing value, the draft workflow status, and that `approve` is offered |
| 3 | `test_api_stability` failed in Phase 1 | `DELETE /api/workspace/members/{id}` returned an empty 204, but the repo requires a JSON response on every route | It returns the removed member (last role) |
| 4 | A Phase 2 test got 429 | Registration is rate-limited to 5 per address, and the test created a 6th account | The test turns an existing member into a second writer through the role-change route |
| 5 | Phase 4: solo users got `REVIEW_REQUIRED` on approve, breaking today's flow | With no AI provider (or any claim not fully supported), drafts need a reviewer, and a solo user has nobody | Solo shortcut (P4, setting `SOLO_REVIEW_SHORTCUT`): a lone approver's approval also stands in for the review, recorded as a self-review. Team workspaces are unaffected |
| 6 | Phase 4: deciding an already-decided review returned `INVALID_TRANSITION` instead of the existing `CONFLICT` | The new workflow check ran before the review's own decidability guard | Reordered so existing responses keep their codes and messages |
| 7 | Phase 4: drafts from before Round 3 would have been stuck | No stored routing for them | `workflow.effective_assessment` computes the routing fresh (with the same rule) when the stored one belongs to an older check |
| 8 | Phase 4: a re-routing test saw no change | The result cache replayed the old verdict | The test clears the cache to simulate a genuinely changed verdict |
| 9 | Phase 4: `approval_denied` recorded the user-facing message instead of the documented reason | A shared `deny()` used the error text | It records "author cannot approve their own content" for self-approval, as in Phase 3 |
| 10 | `REVIEW_REQUIRED` message said "so a reviewer must check…" twice | The message wrapped a routing reason that already said it | The routing reason is used as the message on its own |
| 11 | Verification engine tests couldn't import `jsonschema` | The API venv lacks the engine's dev extras | Ran them in a separate throwaway venv, installed the way their CI installs them: 2004 passed |

## 4. Pulls and merge conflicts

- **Two pulls brought new commits:**
  - `1188453` (Chahit's frontend prompts doc);
  - `cae6fd4` (PR #25, Krish's `krish/round3-prior-work`).
- **Both rebased cleanly, with no conflicts.** After each, the full checklist was re-run and
  passed.
- **One thing flagged:** PR #25 merged a branch whose own commit message says "for reference
  only; not to be merged", and contracts.md §20 says its `unsupported_component` reason is not
  adopted. I did not revert it. It's logged as **P6** for Krish. The backend is unaffected: it
  stores review reasons as-is, routes unknown ones as medium, and doesn't read guard reasons.

## 5. Pending decisions (`DECISIONS_PENDING.md`)

| # | Question | Recommendation |
|---|---|---|
| P1 | Sign-up never verifies email addresses, so "invitee email must match" only proves the account was registered with that address | Accept for Round 3 (the invite link is the secret); add verification plus an email provider before real customers |
| P3 | Krish's Scorecard items 1–3: serve `/latest` from his `summary.json` with `headline`; take the Run button out of the main flow; add per-check ratio fields | OK all three, with item 1 read from a fixed committed path and a 404 "not evaluated" when the file is missing. A draft reply to Krish is in the file |
| P4 | Should a solo user's approval also count as the review a risky draft needs? | Yes (built, behind `SOLO_REVIEW_SHORTCUT=true`); set it to false to make solo users mark drafts reviewed first |
| P5 | The "tone" summary count only covers the engine's two style rules; there is no tone checker yet | Keep, documented; it is one constant in `risk_policy.py` |
| P6 | PR #25 merged a branch marked "not to be merged" | Ask Krish to confirm and update contracts.md, or revert it himself |

Resolved during the run: **P2**. Krish approved contracts.md §19 as written, including D3.

## 6. Known limitations, stubs and next steps

**Limitations:**
- **No real browser.** Browser automation was unavailable in this session. Pages were checked by
  loading each one over HTTP on the production build and reading the server logs, not by
  clicking through in a browser or reading its console.
- **The frontend isn't updated** (Chahit's area; out of scope here):
  - `components/app/roles.ts` still shows every button. It should read `allowed_actions`.
  - There's no UI yet for submit, assign, mark reviewed, publish, members, invitations, the
    workspace switcher or the audit history. Every backend route for these exists and is tested.
  - Naming in Chahit's prompt doc differs from the contract: he writes `risk_state` and
    `summary`; the API sends `risk_level` and `summary_counts`.
  - His list includes a `source_changed` workflow status. The API reports it as `blocked` with
    routing code `source_changed`.
- **Your local database needs migrating** (only throwaway schemas were used):
  `alembic upgrade head` in `services/api` applies 0014–0016. All three are additive. 0014 turns
  `admin` memberships into `owner`. 0015 drops one CHECK constraint (D3).
- **Not built (optional or out of scope):**
  - a `guard_reasons` column for the engine's `citation_guard.rejected[].reason`;
  - transferring a draft's owner;
  - a rate limit on invitations;
  - email delivery of invitations.
- **Unchanged tables:** `approval_events` still records approve, reject and send back only.
  Publish, review and routing live in `audit_events`.
- **Demo data:** the seeded demo accounts are solo workspaces, so they don't show team routing.

**Suggested next steps:**
1. Run `alembic upgrade head` on your dev database.
2. Answer P3 and send Krish the drafted reply; ask him about P6.
3. Hand Chahit the shapes in `contract/examples/governance_*.json` and the field-name notes above,
   so the governance UI can read `allowed_actions`, `workflow_status`, `risk_level`,
   `routing_reason`, `assigned_reviewer` and the audit endpoint.
4. Optionally add a team workspace to the seed script so the demo shows routing with several
   people.
