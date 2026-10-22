# InkLoom AI: Member 3 Context (read before every phase)

You are working for Member 3 (Backend, Security & Governance) on Team CodeNinjas. Do one phase at a time. Each phase file is self-contained but depends on the rules below.

## Working rules
- Build in small steps. After each step show me a diff or summary, then wait.
- Before wiring anything, read the teammates' code and the shared contract in the repo. Never guess their function names, field names or status strings.
- Do not edit files owned by Member 1 (frontend) or Member 2 (engine) without asking me. If the contract must change, propose it, list who it affects, and wait.
- Never commit API keys, `.env` files, private datasets or confidential source material. Provide `.env.example` only.
- Never claim anything is done unless it is integrated and a test proves it. Describe the rest as future work.
- Hackathon rules: only code written in the official build window is judged; disclose AI-generated code and external services. Keep `DISCLOSURE.md` updated.

## Product in one paragraph
InkLoom AI checks content against approved brand knowledge, shows evidence for each finding, suggests safe corrections, and routes uncertain or high-risk content to a human approver. Core principle: missing evidence means `unverified`, never `false`. The AI engine analyses, the backend authorises, the frontend displays. No component takes another's authority.

## Team ownership
- Member 1: frontend (Next.js, React, TypeScript, Tailwind), typed API client.
- Member 2: AI engine (Python, Pydantic, Pytest): retrieval, rules, claims, evidence checks, corrections, evaluation.
- Member 3 (me): database, auth, tenant isolation, API, orchestration, versioning, approval state machine, audit, failure handling, LLM provider adapter.

Open decisions (ask me, do not assume): backend framework (proposal: FastAPI + PostgreSQL); engine in-process (default) or internal HTTP service. Never create a second database for the engine.

## Shared contract values
- Verification status: `supported | contradicted | unverified | conflicting_sources | not_applicable`
- Severity: `low | medium | high | critical`
- Evidence relation: `supports | contradicts | context`
- Review states: `draft, queued, analysing, completed, needs_human_review, changes_requested, approved, rejected, failed, source_changed`. `completed` never means approved.
- Safe errors: stable error code, message without internals, request ID. No stack traces or raw provider errors.

## Governance invariants (server-enforced)
```
if not authenticated or membership not active: deny
if evidence source not in authorised brand scope: reject result, log integrity error
if analysis failed or evidence invalid: block approval
if current_version_id != reviewed_version_id: reject stale approval
if role not allowed to approve, or policy requires another reviewer: deny
never infer approval from a successful AI response
```

## Route map (full list; each phase says which routes it delivers)
| Route | Frontend consumer (Member 1) | Engine (Member 2) |
| --- | --- | --- |
| `POST /api/reviews` | New Review | Starts pipeline |
| `GET /api/reviews/{id}` | Review Results, Evidence Inspector | none |
| `POST /api/content/{id}/versions` | Correction Editor | none |
| `POST /api/reviews/{id}/rerun` | Correction Editor | Same pipeline |
| `GET /api/brands/{id}/sources` | Brand Knowledge | retrieval reads same data |
| `POST /api/brands/{id}/sources` | Brand Knowledge | none |
| `POST /api/content-versions/{id}/approve` | Review Queue | none |
| `POST /api/content-versions/{id}/request-changes` | Review Queue | none |
| `GET /api/content/{id}/history` | Audit History | none |
| `GET /api/analytics/brand-risk` | Dashboard | none |

## Phase order
1. Foundation and contract
2. Auth and tenant scoping
3. Vertical slice (submit → engine → findings → UI)
4. Evidence validation and sources
5. Provider adapter, cache, idempotency, rate limits
6. Versioning, approval and audit
7. Source lifecycle and InkWatch
8. Tests, seed, README, deploy
9. Stretch (only if all above pass)
