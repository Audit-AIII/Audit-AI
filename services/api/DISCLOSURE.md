# Disclosure — backend (Member 3)

Per hackathon rules: only code written in the official build window is judged, and AI-generated
code and external services must be disclosed.

## AI assistance

This service (`services/api`) was built with Claude Code (Anthropic), working from the phase
instructions in [`../../member3_backend/`](../../member3_backend). Claude Code wrote the project
skeleton, SQLAlchemy models, Alembic migrations, structured logging/error handling, the shared
`contract/` files, the LLM provider fallback adapter (`engine/providers/`), the result cache,
idempotency and rate-limiting layers, the approval/versioning/audit state machine, and the
source-lifecycle (withdraw/new-version/section-diff) logic — under this member's direction and
review, and tested against a real Postgres database before being treated as done.

## External services

- **PostgreSQL** — primary datastore. Run locally via `docker-compose.yml`, or any managed
  Postgres in deployment. No application secrets are stored in it — see "Data handling" below.
- **LLM providers (Phase 5)** — the review pipeline's `FallbackProvider`
  (`src/inkloom_api/engine/providers/fallback.py`) tries each configured provider in a fixed
  order, falling through to the next on any failure:
  1. **Google Gemini** (Google AI Studio, free tier) — `GEMINI_API_KEY`.
  2. **Groq** (Llama 3.3 70B / Llama 4 / gpt-oss, free tier) — `GROQ_API_KEY`.
  3. **OpenRouter** `:free` models — `OPENROUTER_API_KEY`.
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
- No other external service is called.

## Data handling

- No API keys, `.env` files, or confidential source material are committed. Only `.env.example`
  is tracked (see `.gitignore`).
- No secrets are stored in the database (see `statuses.py` and the migrations — every table
  holds only operational metadata, content/brand text, and structured, safe details).
- Submitted content and brand source text do leave this process for cloud-provider calls (Gemini
  / Groq / OpenRouter), **except** when any source in the review is marked `confidential`, in
  which case only the local Ollama provider is ever used (Phase 5 task 8).
- The idempotency-replay cache (`idempotency.py`) and rate limiter (`rate_limit.py`) are both
  in-process memory only — correct for this project's single-process demo deployment, reset on
  restart, not shared across multiple worker processes. Documented as a known limitation, not
  hidden.
