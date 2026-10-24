# Decisions

## Decision 1: single-user accounts (24 Oct 2026)

### Decision

InkLoom is a single-user product. One email is one private account. An account owns one or more
brands, and the owner writes, checks and approves their own content.

### Why

- It is the simplest honest fit for the people we are building for: freelancers and small brands
  who check their own content before it goes out.
- The backend is already built this way (`member3_backend/STATUS.md`, section 0): every membership
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
