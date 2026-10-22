# Phase 1: Foundation and contract

Read `00_CONTEXT.md` first.

## Goal
A running backend skeleton, a database with migrations, and a shared contract the whole team uses.

## Do not start until
I have confirmed the backend framework and whether the engine runs in-process. Ask me if the repo does not already show it.

## Tasks
1. Scaffold the project (default: FastAPI + PostgreSQL), config loading from environment, `.env.example`, health check route, structured logging with request IDs.
2. Create migrations for: organisations, users, memberships (role, active flag), brand_profiles, brand_sources (status `draft|approved|superseded|archived`, `sensitivity` `normal|confidential`), source_versions, content_items, content_versions (immutable, version number, content hash), reviews (engine config: provider, model ID, prompt version, schema version), findings, evidence_links, approval_events, audit_events, external_call_log, idempotency_keys, result_cache.
3. Findings store: `finding_id`, `category`, `severity`, `original_text`, `span_start`, `span_end`, `check_type` (rule|retrieval|semantic), `explanation`, `verification_status`, `suggested_correction`, `requires_human_review`. Evidence stores `source_id`, `source_version_id`, `quote`, `relation`.
4. Add foreign keys, unique constraints, indexes. Every tenant-owned record must resolve to an organisation. No secrets in the database.
5. Create `contract/` with the finding and review schema, status strings, role names, and example success and error responses. Tell me what to share with Members 1 and 2.
6. Create `DISCLOSURE.md` and a README stub.

## Wiring with teammates
Check whether Member 1 and Member 2 already have schema or types in the repo. Align field names with theirs; propose changes instead of overriding.

## Done when
- App starts, health check returns OK, migrations run up and down cleanly.
- `contract/` exists and I have reviewed it.
- `.env.example` present, no secrets committed.

## Paste into Claude Code
> Read 00_CONTEXT.md and this file. Confirm the framework decision with me first. Then do tasks 1 to 6 one at a time and show me a summary after each.
