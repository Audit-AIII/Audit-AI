# Phase 8: Tests, seed data, README, deployment

Read `00_CONTEXT.md` first. Requires Phases 1 to 7.

## Goal
Everything is provable, repeatable and demo-ready.

## Tasks
1. One command runs the full test suite. Confirm all of these exist and pass:
   - Org A cannot read or mutate org B's review, source, content or audit records.
   - Changing `organisation_id` in a request body grants nothing.
   - Revoked membership loses access.
   - Invalid transitions and stale-version approvals are rejected.
   - Non-approver gets a safe response, with an audit event where appropriate.
   - Engine output with unknown source IDs, wrong-brand evidence, quote not in source, or invalid schema is rejected.
   - Provider 429, timeout, invalid JSON and all-providers-down never produce an approved state.
   - Duplicate idempotency key creates one job and one LLM call.
   - Same content in two organisations never shares a cache entry.
   - A confidential source produces no external call in the log.
   - Concurrent reviewer actions leave state and audit trail consistent.
   - Edit after approval creates a new version that is not approved.
2. Seed script: one demo organisation, brand, demo users per role, approved sources, and demo content with a terminology violation, a contradicted claim, an unsupported promise and a prompt-injection sample. Label all seeded data as seeded. Use synthetic content only.
3. Smoke test script: create review, fetch findings, request changes, create new version, approve, inspect audit.
4. README: setup, environment variables, migrations, seed, test and run commands, architecture and the engine and frontend integration points, known limitations.
5. `DISCLOSURE.md`: external services (LLM providers, libraries) and AI-assisted code.
6. Deploy to a free host, set environment variables there (never in the repo), tag a known-good release.
7. Fallback demo path: pre-cached demo results and a recorded backup video in case the network or a provider fails.
8. Check that no secrets exist in the repo history or client bundle.

## Wiring with teammates
Run the smoke test against the real frontend and real engine together. List every route and confirm it is integrated or labelled not yet integrated.

## Done when
A first-time user can finish the demo path without developer help, all tests pass in one command, and the tagged release is deployed.

## Paste into Claude Code
> Read 00_CONTEXT.md and this file. First audit which of the listed tests already exist and report gaps. Then fill gaps, then seed, smoke test, README, disclosure, and deployment steps. Show me after each.
