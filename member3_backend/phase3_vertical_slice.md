# Phase 3: Vertical slice (submit → engine → findings → UI)

Read `00_CONTEXT.md` first. Requires Phases 1 and 2.

## Goal
One real review runs end to end: a user submits content, the engine analyses it, findings are saved, and Member 1's UI shows them after a refresh.

## Routes delivered
- `POST /api/reviews`
- `GET /api/reviews/{id}`

## Tasks
1. `POST /api/reviews`: validate input (length, content type, brand belongs to the user's organisation), create the content item and an immutable content version with a canonical hash, create a review in `queued`, return the review ID and status.
2. Run analysis in the background (or synchronously for the first pass; ask me which). Move the review `queued → analysing → completed | needs_human_review | failed`.
3. Read Member 2's engine entry point and schema in the repo. Write an adapter that calls it and maps its output into my findings and evidence tables. If the engine is not ready, use a clearly labelled stub that returns schema-valid sample output, and flag it in the README.
4. `GET /api/reviews/{id}`: return real state, findings, evidence and a safe error code, scoped to the organisation.
5. Publish OpenAPI docs. Enable CORS only for the frontend origin.
6. Write the smoke test: create review, poll until done, fetch findings.

## Wiring with teammates
- Member 1: confirm the response shape matches their typed client exactly; tell me about any field they expect that I do not return. Agree the polling approach.
- Member 2: confirm the function name, input and output schema, and error behaviour (timeout, invalid JSON). Do not guess.

## Rules
`completed` means analysis finished, never approved. If the engine fails or returns invalid output, set `failed`. Never fail open.

## Done when
A review submitted from Member 1's New Review screen shows findings after a page refresh, using the real engine or a labelled stub.

## Paste into Claude Code
> Read 00_CONTEXT.md and this file. First read the Member 1 client types and the Member 2 engine entry point in the repo and report what you found. Then implement tasks 1 to 6 and show me after each.
