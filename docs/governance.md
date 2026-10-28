# Team governance, permissions and risk-based routing (Round 3)

**Status: Phases 1–4 done (2026-10-28); Phases 5–6 proposed.** Owner: Darsh (backend). Sections 1–3
describe the code as found at `1e416e5`; sections 4–10 are the plan. Section 3 lists the open
decisions.

**Progress**

| Phase | State |
|---|---|
| 0. Inspect, plan, contract examples | done (`4326865`) |
| 1. Workspaces, members, invitations | **done**: migration `0014`, `routers/workspace.py`, `workspace_service.py`, `tests/test_workspace_membership.py`. D2 (`admin` → `owner`) and D5 (link shown once) applied as recommended |
| 2. Roles enforced server-side | **done**: role x action table and `can()` in `auth/permissions.py`, used by every route and by `allowed_actions` (`review_queries.review_outs`); `tests/test_permissions.py`, `tests/test_governance_roles.py` |
| 3. Author cannot approve own content | **done**: `approval_service.check_not_self_approval` on the approve route (and, from Phase 4, on publish and the implicit approve); 403 `SELF_APPROVAL_FORBIDDEN` + `approval_denied` audit event, nothing else changes; D1 solo sign-off recorded as `self_approval: true`; `approval_mode` on reviews; `tests/test_self_approval.py` |
| 4. Risk-based routing and workflow | **done**: migration `0015`; `risk_policy.py` (contracts.md §19, approved by Krish 2026-10-28), `workflow_rules.py` (state machine), `workflow.py` (DB side + hooks); routes `POST /api/content/{id}/submit`, `/assign`, `/mark-reviewed`, `POST /api/content-versions/{id}/publish`; reviews carry workspace, author, owner, assigned_reviewer, workflow_status, risk_level, routing_reason, summary_counts; `tests/test_risk_routing.py` |
| 5–6 | not started |

Example payloads for the frontend are in [`contract/examples/`](../contract/examples/), all
starting with `governance_`. Section 9 explains each one.

---

## 1. What exists today

### 1.1 Stack

| Piece | What it is | Where |
|---|---|---|
| Framework | FastAPI | `services/api/src/inkloom_api/main.py` |
| ORM / DB | SQLAlchemy 2 (typed `Mapped[...]`), PostgreSQL via psycopg | `models/`, `db.py` |
| Migrations | Alembic, linear `0001`–`0013` | `services/api/migrations/versions/` |
| Auth | Bearer JWT carrying `user_id` + `organisation_id`. `get_current_membership` reloads the membership on every request and refuses inactive ones | `auth/security.py`, `auth/dependencies.py` |
| Permission hook | `require_permission(Permission.X)` on routes. In individual-user mode it returns True for every known role | `auth/permissions.py` |
| Tenant scoping | `tenancy.py`: fetch by id, then check the row's organisation (or its parent's). A row in another tenant gives the same 404 as a row that does not exist | `tenancy.py` |
| Errors | `{error: {code, message, request_id}}`. The code is derived **from the HTTP status only** | `errors.py` |
| Tests | pytest + FastAPI `TestClient` against real Postgres (skipped without `DATABASE_URL`) | `services/api/tests/` |

**Baseline:** 303 tests pass (throwaway schema `inkloom_test`, 2026-10-28).

### 1.2 Schema (the parts governance touches)

- **`organisations`** (id, name, slug). This is already a workspace: every tenant-owned row
  resolves to one. Registration creates one organisation per user.
- **`users`** (email unique, display_name, password_hash).
- **`memberships`** (organisation_id, user_id, **one** `role`, is_active), unique per pair. The
  role CHECK allows `submitter, source_manager, reviewer, approver, admin, legal_reviewer,
  brand_manager`. Registration writes `admin`, which means "account owner".
- **`brand_profiles`** → organisation_id. **`brand_sources`** → brand_profile_id.
  **`source_versions`** → brand_source_id.
- **`content_items`** (the draft) → organisation_id, brand_profile_id, `created_by` (= author).
- **`content_versions`**: immutable text, `is_current` (exactly one per item), `created_by`.
- **`reviews`**: one AI check run per content version. `status` is the `ReviewState` list:
  `draft, queued, analysing, completed, needs_human_review, changes_requested, approved,
  rejected, failed, source_changed`. It also has `required_reviewer_role` (migration 0008, CHECK
  `legal_reviewer | brand_manager | NULL`), which has been **always NULL** since individual-user
  mode.
- **`findings`** → review_id. Has `verification_status` (**strict CHECK**: `supported,
  contradicted, unverified, conflicting_sources, not_applicable`), `severity` (strict CHECK
  `low..critical`), `category` (free text), `requires_human_review`, `review_reasons` (JSONB,
  stored as-is), and rule fields `rule_id`/`rule_type`.
- **`finding_decisions`** (dismiss/restore), **`finding_comments`**.
- **`approval_events`** (content_version_id, review_id, action `approved|rejected|
  changes_requested`, actor, note).
- **`audit_events`**: append-only, organisation_id, actor_user_id, event_type, entity_type,
  entity_id, details JSONB, request_id.

So most of the "workspace" layer already exists under the name *organisation*. Every brand,
source, draft, finding and audit row already belongs to exactly one, and every existing user
already has a private one. **No data has to move.** The work is roles, invitations, workflow and
routing on top of it.

### 1.3 Endpoints and how each checks access today

Every route resolves the caller's organisation from the token, never from the request. Every
lookup goes through `tenancy.py`, or filters by `organisation_id` directly. Role checks are all
no-ops: `require_permission` passes for every role.

| Endpoint | Reads/writes | Role check today | Scope check today |
|---|---|---|---|
| `POST /api/auth/register` | user, org, `admin` membership, brand | — | — |
| `POST /api/auth/login` | picks the **oldest** active membership | — | — |
| `GET /api/auth/me` | session | any member | token |
| `GET /api/brands` | brands | any member | org filter |
| `POST /api/brands` | brand | `MANAGE_SOURCES` (no-op) | org from token |
| `GET /api/brands/{id}/sources` | sources | any member | `get_brand_profile_or_404` |
| `POST /api/brands/{id}/sources` | source upload | `MANAGE_SOURCES` | brand 404 |
| `POST /api/brands/{id}/sources/{sid}/withdraw` | source status, flips dependents | `MANAGE_SOURCES` | `get_brand_source_or_404` |
| `POST /api/brands/{id}/sources/{sid}/versions` | new source version | `MANAGE_SOURCES` | same |
| `POST /api/brands/{id}/sources/{sid}/approve` | source status | `MANAGE_SOURCES` | same |
| `DELETE /api/brands/{id}/sources/{sid}` | delete draft source | `MANAGE_SOURCES` | same |
| `GET/PUT /api/brands/{id}/rules` | brand rules | any / `MANAGE_SOURCES` | brand 404 |
| `POST /api/reviews`, `POST /api/reviews/upload` | new content item + v1 + AI check | `SUBMIT` (+ rate limit) | brand 404 |
| `GET /api/reviews` | queue list | any member | `reviews_in_organisation` |
| `GET /api/reviews/{id}` | review + findings | any member | `get_review_or_404` |
| `POST /api/reviews/{id}/rerun` | new AI check, same version | `SUBMIT` | `get_review_or_404` |
| `POST /api/content/{id}/versions` | new version + AI check | `SUBMIT` | `get_content_item_or_404` |
| `GET /api/content/{id}/history` | versions, reviews, decisions, finding events | any member | item 404 |
| `POST /api/content-versions/{id}/approve` | **approval** | `APPROVE` (no-op) | `get_content_version_or_404` |
| `POST /api/content-versions/{id}/request-changes` | changes_requested / **rejected** | `REVIEW` (no-op) | same |
| `GET/PUT /api/content-versions/{id}/locks` | intent-lock phrases | any / `SUBMIT` | same |
| `POST /api/findings/{id}/dismiss`, `/restore` | finding decision | `REVIEW` | via review |
| `GET/POST /api/findings/{id}/comments` | comments | any / `REVIEW` | via review |
| `GET /api/analytics/brand-risk` | aggregates | any member | org filter |
| `GET /api/evaluations/latest`, `POST /api/evaluations` | eval runs (cost money) | any member | org filter |

**Every path that can approve or publish today:** only `POST /api/content-versions/{id}/approve`.
There is no generic PATCH-status route, no bulk action, and no publish route. Reject goes
through `request-changes` with `decision: "rejected"`.

### 1.4 AI pipeline signals compared with contracts.md §15–20

What the backend stores per claim finding (`engine/pipeline.py:98-115, 459-564`), compared with
Krish's §19 mapping:

| Engine verdict | Stored `verification_status` | Stored `category` | `severity` | §19 risk |
|---|---|---|---|---|
| `CONTRADICTED` | `contradicted` | `contradicted_claim` | high | **high** → reviewer |
| `NOT_ENOUGH_EVIDENCE` | `unverified` | `unsupported_claim` | medium | **medium** → reviewer |
| `NOT_ENOUGH_EVIDENCE` + conflict | `conflicting_sources` | `unsupported_claim` | medium | **medium** → reviewer |
| `ERROR` | `unverified` | `engine_error` | medium | **medium** → reviewer |
| `SUPPORTED` + any `review_reasons` | `supported`, `requires_human_review=true` | `supported_claim` | low | **low** → reviewer |
| `SUPPORTED`, no reasons | `supported` | `supported_claim` | low | **clean** → approver only |

Everything §19 needs is already stored. No pipeline change is required to compute risk.

---

## 2. Things that conflict with existing code or contracts.md

1. **DECISIONS.md decision 1 (single-user)** and the code built for it:
   - `permissions.py` gives every role every permission.
   - `pipeline._finish` forces `required_reviewer_role = NULL`.
   - The frontend's `roles.ts` returns `true` for everything.
   - `tests/test_individual_mode.py` and `tests/test_permissions.py` pin that behaviour, including
     `test_registered_owner_approves_own_content`.

   Round 3 reverses this. Those tests will be **rewritten, not deleted**: the solo-workspace
   behaviour they check survives in whatever form decision D1 settles.
2. **Self-approval and solo users.** Phase 3 says the author can never approve, owners included.
   But every personal workspace has exactly one member, who is the author of everything in it.
   Applied literally, **no solo user could ever approve anything again**, which breaks today's
   flow (sign-up → brand → upload → check → "Ready to publish"). See D1.
3. **Strict enum on `findings.verification_status` (and `severity`, `check_type`).** Krish asks
   for no strict enums that reject unknown values. Today this is safe only because the backend's
   own mapping is the only writer. Also, `pipeline._STATUS_FOR_VERDICT[verdict]` would raise
   `KeyError` on a new engine verdict. See D3.
4. **Guard reason codes (`property_mismatch`, `unsupported_clause`).** The backend does not
   persist `citation_guard.rejected[].reason` at all today (§20 is right: nothing reads them), so
   they cannot break anything. New **`review_reasons`** values already pass through untouched
   (JSONB). Routing will treat any unknown reason or status as medium risk at minimum.
5. **`reviews.required_reviewer_role` CHECK** only allows `legal_reviewer | brand_manager`. The
   new routing writes its target on the **content item** instead (new column, section 4). See
   section 10 for what the existing `ReviewOut.required_reviewer_role` field will carry.
6. **Error codes come only from the HTTP status** (`errors.py`), so a 403 is always `FORBIDDEN`.
   The handler needs one additive change: an exception may carry its own `code`. Existing
   responses keep their codes (section 8).
7. **contracts.md §15–23 are marked DRAFT/UNAPPROVED**, and the acknowledgement log (§22) is
   empty. I will implement §19 as written, kept in one config module (`risk_policy.py`) so a
   later change touches one file. §19 sends **low** risk (supported but flagged) to the
   **reviewer** queue. The Round 3 brief just says "low risk". I follow §19.
8. **Login picks the oldest membership.** Once a user belongs to several workspaces they need a
   way to switch (section 7). Personal workspaces stay the default, because they are always the
   oldest.
9. **No email sending exists.** An invitation link can't be emailed today. See D5. **No email
   verification exists either:** sign-up accepts any address unchecked. So "invitee email must
   match" only means "the account was registered with that address". Whoever holds the link and
   registers that address first can accept. The link is the real secret until email verification
   is added (not in Round 3 scope; flagged).
10. **"Tone" summary count.** There is no tone or brand-voice checker yet. The closest signals
    are the engine's style rules `all_caps_run` and `emoji_run` (`inkloom_verify/rules.py`,
    "Accessibility and tone"). The count will be that, documented as narrow (section 9.4).

---

## 3. Decisions (Darsh)

**All six decided on 2026-10-28, each as recommended below:** D1 solo sign-off allowed (labelled
self-approval, only while no other member could approve); D2 `admin` → `owner`; D3 drop the
`verification_status` CHECK, unknown statuses stored as-is and routed as medium risk; D4 approve /
send back / reject on a draft do an implicit submit; D5 invite link shown once; D6 no self-review
and reviewer ≠ approver in team workspaces (solo exempt under D1).


| # | Question | Recommendation |
|---|---|---|
| **D1** | Can a user whose workspace has **only them** approve their own content? | **Yes, as a labelled solo sign-off.** Allowed only while the workspace has no other active member who could approve. Recorded as `approval_granted` with `details.self_approval = true, reason = "sole_member"`, and returned as `approval_mode: "self"`. Once a second member with approve rights joins, the rule is strict for everyone, owners included. The alternative ("strict always") means solo users can never approve. |
| D2 | Rename stored role `admin` → `owner` (data update in the migration), or keep `admin` and treat it as an alias? | **Rename to `owner`** and map legacy names in one place. The frontend's `Role` type is open, so `"owner"` won't break it. |
| D3 | Drop the CHECK constraint on `findings.verification_status` so unknown engine statuses can be stored as-is? | **Yes.** Also make the verdict mapping fall back to `unverified` + `requires_human_review` instead of raising. Severity/check_type CHECKs stay: only our own code writes them. |
| D4 | Today's frontend calls approve, send back or reject straight from a checked draft. New flow: draft → submit → decide. | **Any of those three on a `draft` does an implicit submit in the same transaction.** Routing runs first, so a high-risk draft still gets `REVIEW_REQUIRED` on approve. Chahit can add a Submit button whenever. Nothing breaks meanwhile. |
| D5 | How does an invitee get the link without email? | `POST` create-invite returns the raw token and `accept_path` **once** (never stored, never shown again). The owner shares it. The invitee signs up or logs in with that exact email and accepts. |
| D6 | May the author mark their own draft "reviewed"? May one person both mark reviewed and approve the same version? | **No and no** in team workspaces (codes `SELF_REVIEW_FORBIDDEN`, `SAME_REVIEWER_APPROVER_FORBIDDEN`). Both are relaxed only by the D1 solo rule. |

---

## 4. Proposal (a): schema changes and migration

One additive migration, **`0014_workspace_governance`**. It renames nothing and drops no
columns. Workspace = `organisations` row. The API calls it "workspace", and `organisation_id` ==
`workspace_id`.

**`organisations`** (+)
- `is_personal BOOLEAN NOT NULL DEFAULT false`. Backfill `true` for every existing organisation
  (all were created by registration, one per user). The seed org is backfilled `true` only if it
  has a single member.
- `created_by_user_id UUID NULL → users.id`. Backfill: the earliest `admin` member.

**`memberships`** (changed CHECK, no new column)
- Allowed roles become `owner, approver, reviewer, writer`, plus the legacy names kept valid.
- Backfill `admin → owner` (D2). Other legacy names map in code (`permissions.py`):
  `submitter, source_manager → writer`, `legal_reviewer → reviewer`,
  `brand_manager → approver`.
- One role per membership. `owner` holds every capability (section 5).

**`invitations`** (new)
```
id UUID PK, organisation_id → organisations ON DELETE CASCADE, email VARCHAR(320) (lower-cased),
role VARCHAR(20) CHECK (owner|approver|reviewer|writer), token_hash CHAR(64) UNIQUE (sha256 of a
secrets.token_urlsafe(32) token), invited_by_user_id → users, created_at, expires_at (default
now()+7 days), accepted_at NULL, accepted_by_user_id NULL, revoked_at NULL, revoked_by_user_id NULL
UNIQUE (organisation_id, email) WHERE accepted_at IS NULL AND revoked_at IS NULL   -- one pending invite per email
```
An invite that has expired but is still unaccepted and unrevoked counts as pending for this
index. Creating a new invite for that email revokes the expired one in the same transaction.

**`content_items`** (+). The workflow lives on the draft, not on the AI run.
| Column | Type | Notes |
|---|---|---|
| `workflow_status` | VARCHAR(30) NOT NULL DEFAULT `'draft'` | CHECK on our own values (section 6) |
| `owner_user_id` | UUID NULL → users | backfill `created_by` |
| `assigned_reviewer_id` | UUID NULL → users | |
| `risk_level` | VARCHAR(20) NULL | `high, medium, low, clean`. No CHECK |
| `required_reviewer_role` | VARCHAR(20) NULL | `reviewer` or `approver`. No CHECK |
| `routing_reason_code` | VARCHAR(60) NULL | |
| `routing_reason_text` | TEXT NULL | |
| `routing_details` | JSONB NULL | triggering findings (section 7) |
| `routed_content_version_id`, `routed_review_id` | UUID NULL | what the routing was computed from |
| `submitted_by`, `submitted_at`, `reviewed_by`, `reviewed_at` | | |
| `workflow_updated_at` | TIMESTAMPTZ NULL | |

Backfill `workflow_status` from the latest review of the current version:
- `approved` → `approved`
- `rejected` → `rejected`
- `changes_requested` → `needs_changes`
- `failed` / `source_changed` → `blocked`
- anything else → `draft`

Past self-approvals stay as history and are never re-checked.

**`audit_events`** (+)
- `content_item_id UUID NULL` (indexed), `version_number INT NULL`, `note TEXT NULL`. These make
  the per-item audit history a plain indexed query.
- `before`/`after` go in `details`.
- Still append-only: nothing in the app updates or deletes rows. A DB trigger refusing
  UPDATE/DELETE is optional (proposed, cheap).

**`findings`** (D3)
- Drop `ck_finding_verification_status`.
- (+) `guard_reasons JSONB NULL`. Optional: stores `citation_guard.rejected[].reason` values
  as-is if Krish wants them visible.

**Downgrade:** drops the new table and columns, maps `owner → admin`, and restores the CHECKs
after normalising unknown statuses to `unverified`. Same pattern as 0008's downgrade.
`test_migrations.py` covers it.

**Registration:** unchanged response. It also sets `is_personal = true`, `created_by_user_id`,
and the `owner` role.

---

## 5. Proposal (b): roles and permission matrix

**One helper, `governance/authz.py`:**
- `can(auth, action, resource=None) -> Decision(allowed, code, message)`
- `require(auth, action, resource)` raises the right error.
- `allowed_actions(auth, item)` loops over the same function, so the list can never disagree
  with what the server enforces.

`require_permission(...)` on routes is kept and implemented on top of `can()`. Workflow checks
(status, risk, self-approval) live in the same module.

✔ allowed · ✘ refused (403 `FORBIDDEN` unless stated) · "own" = the caller is the item's author
or owner.

| Action (helper name) | Endpoint(s) | writer | reviewer | approver | owner |
|---|---|---|---|---|---|
| `workspace.view` (brands, sources, reviews, history, audit, analytics, eval latest) | all `GET`s in §1.3, `GET /api/content/{id}/audit` | ✔ | ✔ | ✔ | ✔ |
| `brand.create` | `POST /api/brands` | ✘ | ✘ | ✔ | ✔ |
| `source.manage` | `POST …/sources`, `…/versions`, `…/approve`, `…/withdraw`, `DELETE …/sources/{sid}` | ✘ | ✘ | ✔ | ✔ |
| `rules.edit` | `PUT /api/brands/{id}/rules` | ✘ | ✘ | ✔ | ✔ |
| `content.create` | `POST /api/reviews`, `/upload` | ✔ | ✘ | ✘ | ✔ |
| `content.edit` | `POST /api/content/{id}/versions`, `PUT …/locks` | own | ✘ | ✘ | ✔ |
| `content.rerun` | `POST /api/reviews/{id}/rerun` | own | ✔ | ✔ | ✔ |
| `content.submit` / `resubmit` | `POST /api/content/{id}/submit` | own | ✘ | ✘ | ✔ |
| `content.assign` | `POST /api/content/{id}/assign` | ✘ | self only | ✔ | ✔ |
| `finding.comment` | `POST /api/findings/{id}/comments` | ✔ | ✔ | ✔ | ✔ |
| `finding.dismiss` / `restore` | `POST /api/findings/{id}/dismiss`, `/restore` | ✘ | ✔ | ✔ | ✔ |
| `review.request_changes` | `POST …/request-changes` `decision=changes_requested` | ✘ | ✔ | ✔ | ✔ |
| `review.mark_reviewed` | `POST /api/content/{id}/mark-reviewed` | ✘ | ✔ not own (D6) | ✘ | ✔ not own (D6) |
| `content.approve` | `POST /api/content-versions/{id}/approve` | ✘ | ✘ | ✔ not own | ✔ not own |
| `content.reject` | `POST …/request-changes` `decision=rejected` | ✘ | ✘ | ✔ | ✔ |
| `content.publish` | `POST /api/content-versions/{id}/publish` | ✘ | ✘ | ✔ not own | ✔ not own |
| `evaluation.run` | `POST /api/evaluations` | ✘ | ✘ | ✘ | ✔ |
| `members.manage` | invitations + members endpoints (section 7) | ✘ | ✘ | ✘ | ✔ |

**Implemented in Phase 2** (`auth/permissions.py`, `Permission` names in brackets):
every row above except submit, assign, mark_reviewed and publish, whose routes arrive in Phases
3–4. Reading needs only an active membership. The writer's "own" rule covers create_version, locks
and rerun. "not own" on approve/publish: Phase 3, below.

**Phase 3 rule (implemented):** "own" means the caller wrote the draft (`content_items.created_by`)
**or** wrote the version being approved (an owner who edited someone's draft authored that
version). Refused with 403 `SELF_APPROVAL_FORBIDDEN` whenever another active member holds the
approve permission; writers and reviewers don't count. When nobody else could approve (D1), the
approval goes through and its audit event carries `self_approval: true, reason: "sole_member"`.
The check runs before every other approve guard; a refusal rolls the request back and writes only
the `approval_denied` event. Today the approve route is the only path that can approve (there is
no PATCH-status or bulk route); Phase 4's publish route and implicit approve call the same check.

"not own" → 403 `SELF_APPROVAL_FORBIDDEN` (D1 solo rule aside), checked on approve, publish,
the implicit approve of D4, and any future bulk route.

**Escalation rules:**
- Only owners invite or change roles.
- Nobody changes their own role (`SELF_ROLE_CHANGE_FORBIDDEN`).
- A workspace always keeps ≥ 1 active owner (`LAST_OWNER_REQUIRED`, 409, on demote or remove).
- Invites can't name a role the inviter doesn't hold. Owners hold all roles, so in practice only
  owners invite, and they may invite any role.

**Tenant isolation:** unchanged mechanism (`tenancy.py`), plus a test for every new route.
Cross-workspace ids → 404 `NOT_FOUND`, the same message as a random id. Invitations and members
are resolved inside the caller's workspace the same way.

---

## 6. Proposal (c): workflow state machine

`content_items.workflow_status`. Exact values:
`draft, submitted, in_review, needs_changes, reviewed, approved, rejected, published, blocked`.

```
               create / new version (always resets to draft; old approvals stay history)
                                   │
                                   ▼
   AI check failed / source  ┌─► draft ──submit──► routing ─┬─ reviewer required ─► in_review
   changed (any pre-approval │                               └─ clean (approver only) ─► submitted
   state)  ──────────────► blocked ──rerun OK──► draft
                                                                in_review ─mark_reviewed─► reviewed
                                                                in_review ─request_changes─► needs_changes
   submitted | reviewed ─approve─► approved ─publish─► published
   submitted | reviewed ─reject──► rejected
   submitted | reviewed ─request_changes─► needs_changes
   needs_changes ─new version─► draft ─submit (offered as "resubmit")─► routing
```

**As implemented (Phase 4)** — differences from the sketch above:
- A new finished check of the current version re-opens a decided draft (approved, rejected,
  needs changes) as `draft`: the decision belonged to the check it was made on. A failed
  re-check leaves the decision standing; published content stays published.
- Send back and reject act on the current version only (an older version is 409 CONFLICT).
- Approve checks, in order: role, self-approval (D1), the review is decidable (409 CONFLICT, as
  before), the workflow state (REVIEW_REQUIRED / INVALID_TRANSITION / D6), stale version and
  superseded sources (409 CONFLICT).
- **Solo shortcut (P4, setting `SOLO_REVIEW_SHORTCUT`, default on):** when the approver is the
  only person in the workspace who could review or approve, their approval also stands in for
  the review a risky draft needs, recorded as a `reviewed` event with `self_review: true`.
  Without it, a solo user's risky drafts could never be approved through today's UI.

Rules (all server-side, in one transaction with the audit event, the item row locked
`FOR UPDATE`):
- **Approve** is only allowed from:
  - `reviewed`, or
  - `submitted` **with** `required_reviewer_role = approver`.

  From `in_review`, or from a draft whose routing needs a reviewer: 409 `REVIEW_REQUIRED`. Any
  other state: 409 `INVALID_TRANSITION`.
- **Every action names the `content_version_id` it acts on.** If that is no longer current:
  409 `CONFLICT` (the existing stale-version guard, same message as today).
- **Routing re-runs** whenever the current version gets a new completed AI check (rerun, or a
  source change re-check). If the item was `submitted`/`reviewed` and the new risk needs a
  reviewer it didn't have, the item goes back to `in_review`, with a `routing_decision` audit
  event.
- **Approve also keeps the existing guards:**
  - review must be `completed`/`needs_human_review`;
  - version must be current;
  - no cited source superseded.

  On success it updates `reviews.status = approved` and writes `approval_events` exactly as
  today, so the queue, history and Source Watch keep working.
- `blocked` cannot be submitted or approved (409 `INVALID_TRANSITION`, message says why).

---

## 7. Risk routing and membership API

**Rule location:** `services/api/src/inkloom_api/risk_policy.py`. It is a pure function:
`assess(review, findings) -> RiskAssessment(level, required_reviewer_role, reason_code,
reason_text, triggers[])`. Per finding (first match wins):

1. `verification_status == contradicted` → **high** (`contradicted_claim`)
2. `verification_status in {unverified, conflicting_sources}`, or `category == engine_error` →
   **medium** (`unverified_claim` / `conflicting_sources` / `engine_error`)
3. **unknown** `verification_status`, or any `review_reasons` value not in the known list →
   **medium** (`unknown_signal`, the raw value is kept in triggers)
4. `requires_human_review` (claim or rule finding) → **low** (`flagged_for_review`)
5. else → **clean**

Review-level overrides:
- `failed` / `source_changed` → `blocked`.
- Stub (no provider configured) → medium (`not_checked`).
- `rules_status in {incomplete, not_applied}` → medium at least (`rules_incomplete`).

Overall level = the highest one. **clean → `required_reviewer_role = approver`. Anything else →
`reviewer`.** Dismissed findings still count. Dismissing never lowers risk.

**Membership and workspace endpoints** (the workspace always comes from the token):

| Method & path | Who | Result |
|---|---|---|
| `GET /api/workspaces` | any user | my memberships `[{workspace, role, is_personal}]` |
| `POST /api/auth/switch-workspace` `{workspace_id}` | member of it | same shape as login (new token) |
| `GET /api/workspace/members` | any member | `governance_members.json` |
| `PATCH /api/workspace/members/{user_id}` `{role}` | owner | member |
| `DELETE /api/workspace/members/{user_id}` | owner | the removed member (last role) |
| `POST /api/workspace/invitations` `{email, role}` | owner | invitation + raw `token` once |
| `GET /api/workspace/invitations` | owner | list (status computed: pending/accepted/revoked/expired) |
| `POST /api/workspace/invitations/{id}/revoke` | owner | invitation |
| `POST /api/invitations/accept` `{token}` | logged-in user with the invited email | login shape for the new workspace |

**Workflow endpoints** (new): `POST /api/content/{id}/submit`, `/assign`, `/mark-reviewed`,
`POST /api/content-versions/{id}/publish`, `GET /api/content/{id}/audit`.

**Audit events written** (the history API's `action` field):
- `invite_created`, `invite_accepted`, `invite_revoked`
- `member_role_changed`, `member_removed`
- `draft_submitted`, `review_requested`, `routing_decision`
- `changes_requested`, `approval_granted`, `approval_denied`, `approval_rejected`, `reviewed`,
  `reviewer_assigned`, `published`

Existing event types (`review.submitted`, `content_version.approved`, …) keep being written
unchanged. The history API maps the legacy ones to the names above and also returns the raw
`event_type`.

---

## 8. Proposal (d): error codes

Same body as today: `{"error": {"code", "message", "request_id"}}`. New codes are additive. The
frontend's `ErrorCode` type is already open (`lib/api/types.ts:241`).

| HTTP | `code` | When |
|---|---|---|
| 403 | `FORBIDDEN` | role lacks the action (existing code) |
| 403 | `SELF_APPROVAL_FORBIDDEN` | author/owner of the item tries to approve or publish it |
| 403 | `SELF_REVIEW_FORBIDDEN` | author tries to mark own draft reviewed (D6) |
| 403 | `SAME_REVIEWER_APPROVER_FORBIDDEN` | the user who marked it reviewed tries to approve it (D6) |
| 403 | `SELF_ROLE_CHANGE_FORBIDDEN` | changing your own role |
| 403 | `ROLE_ESCALATION_FORBIDDEN` | inviting/assigning a role above your own |
| 403 | `INVITE_EMAIL_MISMATCH` | logged-in email ≠ invited email |
| 404 | `NOT_FOUND` | missing **or other workspace** (existing); also an unknown invite token |
| 409 | `REVIEW_REQUIRED` | approve/publish attempted before required review |
| 409 | `INVALID_TRANSITION` | action not allowed from the current workflow status |
| 409 | `CONFLICT` | stale version, superseded source, review not decidable (existing, unchanged) |
| 409 | `INVITE_EXPIRED` / `INVITE_REVOKED` / `INVITE_ALREADY_USED` | invite lifecycle |
| 409 | `INVITE_ALREADY_PENDING` | a pending invite for this email + workspace exists |
| 409 | `ALREADY_MEMBER` | invitee already in the workspace |
| 409 | `LAST_OWNER_REQUIRED` | would leave the workspace with no owner |
| 422 | `VALIDATION_ERROR` | bad body, unknown role name, assignee not eligible (existing) |

Existing responses keep their codes. The approve route's "review not decidable", "stale" and
"superseded source" stay `CONFLICT`, because the frontend may already branch on them.

---

## 9. API shapes for the frontend (Chahit)

All examples live in `contract/examples/`. The values in them are illustrative only. Real
responses are computed from the database on every request. Nothing is hardcoded.

### 9.1 Review / content item: `governance_review_item_*.json`

Governance fields are **added** to `ReviewOut` (every route that returns it: `GET
/api/reviews`, `GET /api/reviews/{id}`, create, upload, rerun, new version). Every existing field
is unchanged and omitted from the examples for brevity.

| Field | Type | Notes |
|---|---|---|
| `workspace` | `{id, name, is_personal}` | |
| `author` | `{id, display_name}` \| null | `content_items.created_by`. null only on rows with no author. `display_name` falls back to the email's local part, never the full email |
| `owner` | `{id, display_name}` \| null | `content_items.owner_user_id` |
| `assigned_reviewer` | `{id, display_name}` \| null | **null in personal workspaces** and whenever nobody is assigned. Show "not assigned" |
| `workflow_status` | one of `draft, submitted, in_review, needs_changes, reviewed, approved, rejected, published, blocked` | treat unknown as "in progress" |
| `risk_level` | `high, medium, low, clean` \| null | null until the AI check finishes |
| `routing_reason` | `{code, text, triggered_by: [{finding_id, verification_status, review_reasons, risk_level}]}` \| null | |
| `required_reviewer_role` | `"reviewer"` \| `"approver"` \| null | **value set widened** (section 10) |
| `approval_mode` | `"team"` \| `"self"` | `"self"` = D1 solo sign-off |
| `allowed_actions` | string[] | section 9.2 |
| `summary_counts` | object | section 9.4 |
| `is_current_version` | bool \| null | the reviewed version is the draft's current one. On an older version `approve` is never listed; edit, re-check, comment and dismiss still are, because their routes accept them |

Examples:
- `governance_review_item_team_writer.json`: writer looking at their own high-risk draft
  (`in_review`). **No `approve`.**
- `governance_review_item_team_approver.json`: approver looking at a reviewed item.
- `governance_review_item_personal.json`: solo workspace. `assigned_reviewer: null`,
  `approval_mode: "self"` (assuming D1 = yes).

### 9.2 `allowed_actions[]`

Exact values, computed by the same `can()` the server enforces:
- `submit`, `resubmit`, `create_version`, `rerun`
- `assign`, `mark_reviewed`, `request_changes`
- `approve`, `reject`, `publish`
- `comment`, `dismiss_finding`

Live since Phase 2, each listed only when the role allows it (`can()`) **and** the route would
accept it now:

| Action | Extra condition (same as the route) |
|---|---|
| `create_version`, `rerun` | writers: only on drafts they wrote |
| `approve` | the latest review of the draft's **current** version, status `completed`/`needs_human_review` |
| `request_changes`, `reject` | the latest review of its version, status `completed`/`needs_human_review` |
| `comment`, `dismiss_finding` | none (any review) |

`submit`, `resubmit`, `assign`, `mark_reviewed` and `publish` appear once their routes exist
(Phases 3–4). Phase 3 also removes `approve` from the author's own drafts.

The frontend shows a control only when its action is in the list, and must still handle a
403/409 (state can change between load and click). Treat an unknown value as unknown.

### 9.3 Audit history: `governance_audit_history.json`

`GET /api/content/{content_item_id}/audit?limit=20&cursor=<opaque>`. Newest first, `limit`
1–100 (default 20). `next_cursor` is null on the last page.

Item shape: `{id, actor: {id, display_name} | null (null = system), action, event_type,
note, version_number, created_at, details}`.

The existing `GET /api/content/{id}/history` stays unchanged.

### 9.4 Summary counts

Computed server-side over the findings of the review being returned:

| Key | Counts |
|---|---|
| `supported` | `verification_status = supported` |
| `contradicted` | `= contradicted` |
| `unverified` | `= unverified` (includes engine errors) **plus any unknown status** |
| `conflicting` | `= conflicting_sources` |
| `tone` | rule findings with `rule_type in {all_caps_run, emoji_run}`. **Narrow**: there is no tone checker yet. The set lives in `risk_policy.py` |
| `needs_human_review` | `requires_human_review = true` |

Dismissed findings are still counted. These are counts of real findings, never metrics.

### 9.5 Errors: `governance_errors.json`

One example body per new code, with its HTTP status.

### 9.6 Membership / invitations

`governance_members.json`, `governance_invitation_created.json`,
`governance_invitations_list.json`, `governance_invite_accept.json`.

---

## 10. Contract changes (to confirm with the team before merging)

1. **`ReviewOut.required_reviewer_role`.** Today always null, and typed in the frontend as
   `"legal_reviewer" | "brand_manager" | null` (open). It will carry `"reviewer"`, `"approver"`
   or null. The UI currently shows null as "Any approver".
2. **New `ReviewOut` fields** (section 9.1). Additive.
3. **`role` in login/register/me** becomes `"owner"` for owners instead of `"admin"` (D2).
   Additive on `/me`: `workspace.is_personal`, `memberships_count`.
4. **New error codes** (section 8). Additive. Existing codes unchanged.
5. **Behaviour change:** approve can now return 403 `SELF_APPROVAL_FORBIDDEN` and 409
   `REVIEW_REQUIRED` (team workspaces). Writers/reviewers get 403 on routes that were open to
   them. Solo users see no change if D1 = yes and D4 = implicit submit.
6. **No engine contract change.** Nothing here touches `inkloom_verify` payloads. Unknown
   statuses and reasons are stored and passed through.

---

## 11. Test plan (Phase 6, summary)

New fixtures:
- one team workspace with separate **writer, reviewer, approver, owner** users;
- an **outsider** in another workspace.

The current `account_factory` stays for solo flows. Coverage:
- every role × action in section 5 against the real endpoint;
- `allowed_actions` == the set of actions that actually succeed;
- outsider gets 404 on every new and existing id route;
- invitation lifecycle: create, accept, duplicate, unknown, expired, revoked, reused, wrong email,
  role escalation, self role change, last owner;
- self-approval refused on approve, implicit approve and publish, with the state unchanged and
  an `approval_denied` event written;
- routing: contradicted → `REVIEW_REQUIRED` until reviewed; clean → approver only; `property_mismatch`,
  `unsupported_clause` and a made-up reason/status → medium, no crash;
- an audit event for each action;
- one end-to-end run with four users;
- the existing 303 tests, with `test_individual_mode.py` and `test_permissions.py` rewritten to
  the new solo rules.
