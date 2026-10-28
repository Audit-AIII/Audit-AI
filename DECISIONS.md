# Decisions

## Decision 1: single-user accounts (24 Oct 2026) — superseded by Decision 2

### Decision

InkLoom is a single-user product. One email is one private account. An account owns one or more
brands, and the owner writes, checks and approves their own content.

### Why

- It is the simplest honest fit for the people we are building for: freelancers and small brands
  who check their own content before it goes out.
- The backend is already built this way ([`docs/backend.md`](docs/backend.md), "Product model"): every membership
  holds every permission, risk routing is off, and `required_reviewer_role` is always empty.
- It avoids shipping half-built role workflows before the deadline. A screen that talks about
  reviewers and managers who do not exist would be a claim the product cannot back up.

### What it means

- One owner per account. Nobody else can see or change its brands, documents or reviews.
- The owner approves their own content. There is no second approver.
- Nothing is ever approved automatically. Approve, send back and reject each need an explicit
  click from the owner.
- Every decision is saved in the audit log: who decided, when, and which version of the draft.
- An old approval never carries over to a newer version of the same draft.

### What changed from the Round 1 plan

The Round 1 plan had separate creator, reviewer and manager roles, plus risk-based routing (risky
drafts to a reviewer, clean drafts to a manager). These are **deferred, not built**. The database
columns for them stay in place so they can come back later without a migration.

### Deferred to the roadmap

- Multi-user accounts and invites
- Reviewer tiers (reviewer, approver, legal reviewer, brand manager)
- Risk-based routing
- An "author cannot approve their own content" rule

## Decision 2: personal workspace by default, optional team members (28 Oct 2026)

### Decision

Every account still starts as one person's private **personal workspace**: sign up with any email,
create brands, check drafts, exactly as before. On top of that, a workspace owner can invite other
people into it with one role each: **owner, approver, reviewer or writer**. Roles are enforced by
the backend on every request, never only by hiding buttons in the UI.

### Why

- Round 3 commits to team governance: separate writers, reviewers and approvers, risky drafts
  routed to a reviewer, and nobody approving their own work.
- The backend already scoped every brand, document, draft, finding and audit record to one
  organisation per account, so a workspace is that organisation. No existing data moves, and
  people who never invite anyone see no change.

### What it means

- Sign-up creates a personal workspace where the user is `owner`. Existing accounts became owners
  of their existing workspace (migration 0014; `admin` rows became `owner`).
- Invitations are bound to one workspace, one email and one role, expire after 7 days, and work
  once. No email is sent yet: the owner shares the link.
- A person can belong to several workspaces and switch between them. Nobody sees another
  workspace's data: an id from another workspace answers "not found".
- Every membership change is in the audit log.

### Being built in Round 3 (docs/governance.md)

- Phase 2: the full role × action table, enforced server-side, and `allowed_actions` per draft.
- Phase 3: an author cannot approve or publish their own content, owners included. How this works
  for someone alone in their workspace is open decision D1 in `docs/governance.md`.
- Phase 4: risk-based routing from the verification results (contracts.md section 19).
- Phase 5: the audit events for each workflow step.
