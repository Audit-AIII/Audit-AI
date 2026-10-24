# Disclosure — backend (Member 3)

Per hackathon rules: only code written in the official build window is judged, and AI-generated
code and external services must be disclosed.

## AI assistance

This service (`services/api`) was built with Claude Code (Anthropic), working from phase
instructions that were kept in `member3_backend/` (removed from the tree; still in git history,
and their lasting decisions are in [`../../docs/backend.md`](../../docs/backend.md)). Claude Code
wrote the project skeleton, SQLAlchemy models, Alembic migrations, structured logging/error handling, the shared
`contract/` files, the LLM provider fallback adapter (`engine/providers/`), the result cache,
idempotency and rate-limiting layers, the approval/versioning/audit state machine, and the
source-lifecycle (withdraw/new-version/section-diff) logic — under this member's direction and
review, and tested against a real Postgres database before being treated as done. The individual-user round (2026-10-24: individual-account mode, finding categories, suggested
corrections, review queue, analytics, Trust Scorecard, scripted demo provider, seed rewrite) was
also written with Claude Code under the same direction, with every change committed separately.

## External services

- **PostgreSQL** — primary datastore. Run locally via `docker-compose.yml`, or any managed
  Postgres in deployment. No application secrets are stored in it — see "Data handling" below.
- **LLM providers (Phase 5)** — the review pipeline's `FallbackProvider`
  (`src/inkloom_api/engine/providers/fallback.py`) tries each configured provider in a fixed
  order, falling through to the next on any failure:
  1. **Google Gemini** — `GEMINI_API_KEY`, used **only with `GEMINI_PAID_TIER=true`** on a paid
     key: free-tier prompts may be used by Google to improve its products, so a free key is
     refused.
  2. **Groq** — `GROQ_API_KEY` (no extra gate in this backend; check Groq's data terms).
  3. **OpenRouter** — `OPENROUTER_API_KEY`, with `INKLOOM_LLM_DATA_COLLECTION=deny` by default
     (only providers that don't collect prompts).
  Which keys are actually configured is not decided yet; see `AI_PROVIDER_KEYS.md`.
  4. **Local Ollama** — no key, nothing leaves the machine. The *only* provider ever used for a
     review whose corpus includes a `confidential` brand source (`build_provider(confidential=
     True)` never even constructs a cloud provider builder — proven in
     `tests/test_phase5_cache_idempotency_confidential.py` by making the cloud builders raise if
     invoked).
  - None are required: with none configured, `POST /api/reviews` still completes, writing one
    clearly-labelled stub finding instead of a real one.
  - Only provider/model identity, latency and a safe error code are logged
    (`external_call_log`) — never prompt content, completions, or raw provider error bodies.
  - A result that is served from the cache (`result_cache.py`) makes no external call at all,
    confidential or not.
  - What each kind of call sends (every one through the same chain, logged as above):
    - **Claim extraction:** the draft's text.
    - **Verification:** one claim and the passages retrieved for it from the brand's approved
      documents.
    - **Correction** (contradicted claims): the author's sentence, the claim and the cited source
      quotes; then the corrected claim with the same passages (the engine's re-check).
    - **Safer wording** (unverified claims; the engine's `ClaimSoftener`): the sentence and the claim.
  - Sent to no model: **brand rules** (terminology, compliance, accessibility run locally and
    deterministically) and **Intent-lock phrases** (checked locally by the engine and again by
    this backend; they are not part of any prompt). Dismissals and comments stay in the database.
  - `POST /api/evaluations` (Trust Scorecard) sends the engine's synthetic labelled test claims and
    their synthetic reference documents (`services/verification/eval/dataset.jsonl`) through the
    same chain - no user content. Calls are logged with request id `eval-<run id>`.
  - `scripts/seed.py` and the test suite make no provider call: they use the stub or the offline
    scripted provider (`src/inkloom_api/engine/scripted_provider.py`, model id `scripted/demo-v1`).
- No other external service is called.

## Data handling

- No API keys, `.env` files, or confidential source material are committed. Only `.env.example`
  is tracked (see `.gitignore`).
- No secrets are stored in the database (see `statuses.py` and the migrations — every table
  holds only operational metadata, content/brand text, and structured, safe details).
- Submitted content and brand source text do leave this process for cloud-provider calls (Gemini
  / Groq / OpenRouter), **except** when any source in the review is marked `confidential`, in
  which case only the local Ollama provider is ever used (Phase 5 task 8).
- The rate limiter (`rate_limit.py`) is in-process memory only - correct for a single-worker
  deployment (the Dockerfile and `scripts/start.sh` run exactly one), reset on restart.
  Idempotency keys (`idempotency.py`) are stored in the database.
- On a cloud host without Ollama, a review whose brand has a `confidential` document **fails
  closed**: no cloud provider is tried, the review gets the labelled stub finding, and nothing
  leaves the server.
