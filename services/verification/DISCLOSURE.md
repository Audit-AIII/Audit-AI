# Disclosure: AI verification engine (Member 2, Krish)

This file covers `services/verification` and its evaluation data. The backend has its own
[`services/api/DISCLOSURE.md`](../api/DISCLOSURE.md). **DRAFT: Krish must read this, correct
anything that is not true for his own work, and then remove this line.** Every member has to state
their own role accurately.

## AI assistance

The engine was written with **Claude Code (Anthropic)** under Krish's direction and review, from
the phase instructions in `CLAUDE.md` and `docs/`. Claude Code wrote the Python modules (contracts,
retrieval, extraction, verification, citation guard, correction, softening, rules, scoring, security
checks), the tests, the evaluation harness and these documents. Every change is committed and was
checked by running the test suite before it was treated as done.

## External services

- **OpenRouter** (`providers/openrouter.py`, over `httpx`): the only model provider the engine
  implements. The model ids come from the `INKLOOM_LLM_MODELS` environment variable and are not
  hard-coded. API keys stay in local `.env` files and are never committed or logged
  (`tests/test_security.py` checks this).
- The backend (`services/api`) separately calls Gemini, Groq, OpenRouter and a local Ollama model.
  That is Member 3's disclosure.
- The engine's tests and the default evaluation run make **no network calls**: they use a scripted
  fake provider.

## Libraries and licences

| Library | Used for | Licence |
|---|---|---|
| pydantic >=2.10 | schemas and validation | MIT |
| rank_bm25 >=0.2.2 | evidence retrieval (BM25) | Apache-2.0 |
| httpx >=0.27 | OpenRouter calls | BSD-3-Clause |
| FastAPI, uvicorn (optional `api` extra) | optional HTTP wrapper | MIT, BSD-3-Clause |
| pytest, jsonschema, pip-audit (dev only) | tests, schema checks, dependency audit | MIT, MIT, Apache-2.0 |

No third-party source code was copied into `services/verification`.

## Datasets

All evaluation data is **synthetic**. It describes a fictional company, Lumen Goods (Lumen Pods
earbuds and the Lumen Bottle), with invented reference documents, including two that carry prompt
injections. It was written with Claude Code. No real company, person or customer data is used.
Provenance is recorded in `EVAL.md`.

## What the engine does and does not claim

- It checks claims against **approved reference text it is given**. It does not know whether a
  claim is true in the world, and `NOT_ENOUGH_EVIDENCE` is the default when evidence is missing.
- Rules are deterministic, need no model, and never auto-approve: every finding asks for human
  review (RULES_HANDOFF.md). They cover terminology (required, prohibited, preferred terms,
  spelling, product names, consistency), brand compliance (disclaimers, numeric limits), and
  accessibility and tone (alt text, link text, headings, captions, colour contrast, ALL-CAPS and
  emoji runs). Checks that lack data report "not checkable", never "passed".
- Intent-lock is enforced by code, not by prompt wording: a suggested correction or safer wording
  that would remove a locked phrase is refused (`intent_lock.py`).
- **Measured accuracy of a live model has not been established yet.** The default evaluation is
  an always-abstain floor and the scripted adversaries test what the code enforces, not model
  quality. Any live-model number must be reported with its sample size and what it covers (see
  `EVAL.md`).
- The accessibility and tone checks are heuristics for English text (emoji are recognised by
  Unicode block, ALL-CAPS by word runs), so they can miss cases and can flag acronyms unless
  `allowed_caps` lists them.
- Input is plain text. Parsing uploads and images is outside this module.

## Contribution (draft for Krish to confirm)

From the commit history, Krish owns `services/verification`: the engine, its tests and CI
(`.github/workflows/verification-engine.yml`), the synthetic evaluation datasets and harness
(`eval/`), the rules and softening modules, and the repo integrity check added in PR #1. Krish
should rewrite this paragraph in his own words, with anything the history does not show.
