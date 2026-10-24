# InkLoom AI · "Audit AI"

Audit AI checks content **before it is published** against a brand's own approved documents
(brand guide, fact sheet, product specs). Every finding shows the evidence it is based on: the
exact quote from the approved document. When no approved document covers a claim, the claim is
marked **"unverified"**, never "false". Audit AI only suggests; **a person makes the final call**
on every draft.

Built by team **CodeNinjas** for the Inkloom AI hackathon.

## Product decision: single-user accounts

One email is one private account that owns one or more brands. The owner writes, checks and
approves their own content; nothing is ever approved for them, and every decision is saved with
who, when and which version. Roles, risk routing and invites are deferred to the roadmap. See
[DECISIONS.md](DECISIONS.md) for the reasoning.

## Built today vs planned

| Built today | Planned |
|---|---|
| Factual-claim checking: claims in a draft are extracted and checked against the brand's approved documents (supported / contradicted / unverified), with the quote behind each verdict | Tone checks |
| Upload brand documents (PDF, Word, text) and drafts (paste or upload) | Terminology (wording) checks: engine module built and tested, not yet run in reviews |
| Decide on each review: approve, send back with a note, or reject; every decision is recorded | Accessibility checks (alt text, link text, headings, captions, contrast): engine module built and tested, not yet run in reviews |
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

## How verdicts are made: deterministic checks vs model assessments

| Step | Deterministic (no model) | Uses a language model |
|---|---|---|
| Evidence retrieval | BM25 over the brand's **approved** documents only | |
| Claim extraction | spans and atomicity checked against the draft | proposes claims |
| Verdict | | proposes supported / contradicted / not enough evidence, with quotes |
| Citation guard | every quote must exist verbatim in a retrieved passage of an authorised document; instruction-like text is never evidence; conflicting documents downgrade the verdict | |
| Corrections | added words and figures must come from the cited quote; the fix is re-verified; Intent-lock phrases may not be removed | proposes the fix |
| Rules (engine) | terminology, disclaimers, numeric limits, accessibility | |

Anything the model says that fails a deterministic check is downgraded, never trusted. Provider
errors and invalid output become "unverified, needs review", never a verdict. Every non-supported
finding goes to a person.

## Evaluation

The engine has a labelled, synthetic benchmark (80 records: 55 dev, 25 held-out) and a runner that
writes reports to `services/verification/eval/reports/`. From `services/verification`:

```sh
.venv/Scripts/python -m pytest -q                                  # engine tests (no network)
.venv/Scripts/python eval/run_eval.py --check-baseline             # CI gates (no model)
.venv/Scripts/python eval/run_eval.py --verdicts oracle --check-baseline   # engine ceiling (scripted gold answers)
.venv/Scripts/python eval/run_eval.py --verdicts openrouter --pipeline verifier --check-baseline  # live model
```

**No live-model accuracy has been established.** The oracle and default runs measure what the code
enforces, not a model. Live runs so far were blocked by provider availability (see
[`services/verification/EVAL.md`](services/verification/EVAL.md), "Live evaluation status").

## AI-assistance disclosure

- **Frontend:** written with Claude Code (Anthropic) under the direction of Chahit, who reviewed
  and tested it.
- **Backend:** TODO: Darsh to fill in.
- **Verification engine:** written with Claude Code (Anthropic) under Krish's direction and review; details,
  libraries and datasets in [`services/verification/DISCLOSURE.md`](services/verification/DISCLOSURE.md)
  (draft: Krish to confirm).

## Style reference

The visual style ("pressed paper") is inspired by the public style of
[relevovinco.com](https://relevovinco.com). It was re-implemented from scratch; no text, images,
code or brand assets were copied.

## Contributions

| Person | Area | |
|---|---|---|
| Chahit | Frontend | TODO: confirm |
| Darsh | Backend API | TODO: confirm |
| Krish | AI verification engine (`services/verification`): claim extraction, evidence retrieval, verification, citation guard, corrections, softening, Intent-lock checks, terminology/accessibility rules, evaluation harness | Krish to confirm |

## Known limitations

From `member3_backend/STATUS.md` §10, plus two frontend notes:

- The rate limiter and idempotency replay live in process memory (single worker only). The
  evaluation's 10-minute limit is stored in the database.
- No invites, organisation switcher, password reset or email verification (by design: accounts are
  individual).
- The engine's softening step (a safer wording for unverified claims) exists, but the backend currently
  stores its output as a suggested correction; it should be a separate field labelled "not
  evidence-backed" ([handoff, gap 2](services/verification/HANDOFF_STEPS_6_8.md)).
- Terminology and accessibility rules exist in the engine but the backend does not run them in
  reviews yet ([`RULES_HANDOFF.md`](services/verification/RULES_HANDOFF.md)).
- Source conflict detection and later stretch items are not built.
- Not deployed.
- **Trust Scorecard numbers measure the verifier only**, on a labelled benchmark set. They are not
  live statistics about your content.
- **Accounts are single-user:** one email is one private account that writes, checks and approves
  its own content.
- Must-keep text (Intent-lock) in the correction editor is saved in the browser only. The engine refuses
  any suggestion that would remove locked text when it is given the locks, but the server does not
  store or pass them yet ([handoff](services/verification/HANDOFF_STEPS_6_8.md)).

## Roadmap

1. Tone, terminology, accessibility and visual checks (shown as "Coming next" today).
2. Show the engine's safer rewrite for unverified claims as its own, labelled suggestion.
3. Local Ollama set up for confidential documents.
4. Comments on findings.
5. Multi-user accounts and invites.
6. Separate reviewer and approver roles, including an "author cannot approve" rule.
7. Risk-based routing (risky drafts to a reviewer).
8. Deployment.
