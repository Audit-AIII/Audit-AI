# Disclosure — backend (Member 3)

Per hackathon rules: only code written in the official build window is judged, and AI-generated
code and external services must be disclosed.

## AI assistance

This service (`services/api`) was scaffolded with Claude Code (Anthropic), working from the
phase instructions in [`../../member3_backend/`](../../member3_backend). Claude Code wrote the
project skeleton, SQLAlchemy models, Alembic migrations, structured logging/error handling, and
the shared `contract/` files, under this member's direction and review.

## External services

- **PostgreSQL** — primary datastore. Run locally via `docker-compose.yml`, or any managed
  Postgres in deployment.
- No other external service is called by this phase. The LLM provider (OpenRouter, via Member
  2's engine) is wired in a later phase; see `services/verification/.env.example`.

## Data handling

- No API keys, `.env` files, or confidential source material are committed. Only `.env.example`
  is tracked (see `.gitignore`).
- No secrets are stored in the database (see `statuses.py` and the migration — every table holds
  only operational metadata, content/brand text, and structured, safe details).
