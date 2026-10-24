# InkLoom AI · "Audit AI"

Audit AI checks content **before it is published** against a brand's own approved documents
(brand guide, fact sheet, product specs). Every finding shows the evidence it is based on: the
exact quote from the approved document. When no approved document covers a claim, the claim is
marked **"unverified"**, never "false". Audit AI only suggests; **a person makes the final call**
on every draft.

Built by team **CodeNinjas** for the Inkloom AI hackathon.

## Built today vs planned

| Built today | Planned |
|---|---|
| Factual-claim checking: claims in a draft are extracted and checked against the brand's approved documents (supported / contradicted / unverified), with the quote behind each verdict | Tone checks |
| Upload brand documents (PDF, Word, text) and drafts (paste or upload) | Terminology (wording) checks |
| Decide on each review: approve, send back with a note, or reject; every decision is recorded | Accessibility (readability) checks |
| Versions: edit a draft, save a new version, check it again; an old approval never applies to a newer version | Visual (logo and colour) checks |
| Source Watch: withdrawing or replacing an approved document sends dependent approvals back for review | Comments on findings |
| Trust Scorecard: benchmark results of the verifier, from the engine's evaluation runner | Multi-user roles (separate writers, reviewers, approvers) |

The landing page marks the four planned checks as "Coming next".

## Architecture

| Part | Folder | Stack |
|---|---|---|
| Frontend | `audit-ai-final/frontend` | Next.js (App Router), React, TypeScript, Tailwind v4, GSAP, Lenis (landing page only) |
| Backend API | `services/api` | FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 |
| Verification engine | `services/verification` | `inkloom_verify` (Python package): claim extraction, BM25 evidence retrieval, verification, citation guard, corrections |

How a review flows:

```
Browser (Next.js)
  │  paste text or upload a file
  ▼
FastAPI  POST /api/reviews  ──►  stores a content version (PostgreSQL)
  │
  ▼
inkloom_verify
  1. extract claims from the draft      (LLM)
  2. retrieve evidence passages          (BM25 over the brand's APPROVED documents)
  3. verify each claim against them      (LLM) → supported / contradicted / unverified
  4. check every citation is a real quote, propose evidence-backed corrections
  │
  ▼
FastAPI stores findings + evidence  ──►  Browser shows each finding with its quote
                                          a person approves / sends back / rejects
```

No AI provider configured? Reviews still complete, with one clearly labelled placeholder finding
instead of a real check.

## Setup and run

Requirements: Python 3.11+, Node.js, Docker Desktop (for PostgreSQL). Commands below are from
`services/api/README.md` and `services/verification/README.md`; on macOS/Linux use
`.venv/bin/python` instead of `.venv/Scripts/python`.

**1. Backend** (from `services/api`)

```sh
cp .env.example .env            # then set AUTH_SECRET_KEY (see the comment in the file)
docker compose up -d            # local PostgreSQL
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pip install -e ../verification
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python scripts/seed.py          # demo data
.venv/Scripts/python -m uvicorn inkloom_api.main:app --reload
```

The API runs on http://localhost:8000 (interactive docs at `/docs`). Seed data is labelled
`[SEEDED]` in its names, and the script prints the demo login. A full `pytest` run wipes it; run
`scripts/seed.py --reset` afterwards.

**2. Frontend** (from `audit-ai-final/frontend`)

```sh
cp .env.example .env.local      # only NEXT_PUBLIC_API_URL; never put secrets here
npm install
npm run dev
```

Open http://localhost:3000. The backend only accepts browser calls from that address by default
(`CORS_ALLOW_ORIGINS`).

**3. Engine tests** (from `services/verification`)

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```

No secrets are committed. Every setting is documented in the `.env.example` files:
`services/api/.env.example`, `services/verification/.env.example`,
`audit-ai-final/frontend/.env.example`.

## Models and external services

All optional; set in `services/api/.env`. The backend tries them in this fixed order and falls
through to the next on any failure:

1. **Google AI Studio (Gemini)**: `GEMINI_API_KEY`, `GEMINI_MODEL`
2. **Groq**: `GROQ_API_KEY`, `GROQ_MODEL`
3. **OpenRouter** (`:free` models): `OPENROUTER_API_KEY`, `INKLOOM_LLM_MODELS`
4. **Local Ollama**: `OLLAMA_MODEL` (no key, nothing leaves the machine)

With a key set, draft text is sent to that provider. Documents marked **confidential** are meant
to stay on the local model (Ollama), which is the only provider allowed for them; Ollama is not
set up in the current environment. Model ids change over time, so read them from each provider's
live model list (the `.env.example` comments explain how).

## AI-assistance disclosure

- **Frontend:** written with Claude Code (Anthropic) under the direction of Chahit, who reviewed
  and tested it.
- **Backend:** TODO: Darsh to fill in.
- **Verification engine:** TODO: Krish to fill in.

## Style reference

The visual style ("pressed paper") is inspired by the public style of
[relevovinco.com](https://relevovinco.com). It was re-implemented from scratch; no text, images,
code or brand assets were copied.

## Contributions

| Person | Area | |
|---|---|---|
| Chahit | Frontend | TODO: confirm |
| Darsh | Backend API | TODO: confirm |
| Krish | AI verification engine | TODO: confirm |

## Known limitations

From `member3_backend/STATUS.md` §10, plus two frontend notes:

- The rate limiter and idempotency replay live in process memory (single worker only). The
  evaluation's 10-minute limit is stored in the database.
- No invites, organisation switcher, password reset or email verification (by design: accounts are
  individual).
- Unverified claims get no suggested wording until the engine's softening step ships.
- Source conflict detection and later stretch items are not built.
- Not deployed.
- **Trust Scorecard numbers measure the verifier only**, on a labelled benchmark set. They are not
  live statistics about your content.
- **Accounts are single-user:** one email is one private account that writes, checks and approves
  its own content.
- Must-keep text in the correction editor is saved in the browser only; the server does not enforce it.

## Roadmap

1. Tone, terminology, accessibility and visual checks (shown as "Coming next" today).
2. A suggested safer rewrite for unverified claims.
3. Local Ollama set up for confidential documents.
4. Comments on findings.
5. Multi-user workspaces with separate reviewer and approver roles.
6. Deployment.
