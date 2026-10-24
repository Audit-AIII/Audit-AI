# AI provider keys: what each part needs

Which API keys the AI parts of InkLoom need, where each is set, and what happens without them.
**No keys are chosen yet** (2026-10-24): this lists the options. Never commit a real key - set it
in `services/api/.env` locally (gitignored) or in the host's secret settings when deployed.

## What needs a key, and what doesn't

| Part | Needs an AI key? | Without one |
|---|---|---|
| Backend reviews (`POST /api/reviews`, re-check, new version): claim extraction, verification, corrections, safer wording | **Yes, at least one provider** | Works, but every review is one clearly labelled `[STUB OUTPUT]` placeholder finding; no claim is checked |
| Trust Scorecard run (`POST /api/evaluations`) | **Yes** (about 80-150 model calls per run) | `409`: "no AI provider is configured" |
| Engine CLI evaluation (`services/verification/eval/run_eval.py --verdicts openrouter`) | **Yes, OpenRouter only** | Use `--verdicts oracle` (scripted benchmark, no key) |
| Brand rules (terminology, compliance, accessibility) | No (deterministic) | Always runs |
| Intent-lock, Dismiss, comments, Source Watch, versions, approvals | No | Always works |
| Tests, CI, demo seed (`scripts/seed.py`) | No (offline scripted provider) | Always works |

## The four providers (backend, tried in this order)

The backend tries each configured provider in turn and falls through to the next on any failure
(`src/inkloom_api/engine/providers/fallback.py`). Configure one or several.

| # | Provider | Settings | Get a key | Free? | Privacy rule in this project |
|---|---|---|---|---|---|
| 1 | Google Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_PAID_TIER` | https://aistudio.google.com/apikey | Free tier exists | **Used only with `GEMINI_PAID_TIER=true` on a paid key.** Free-tier prompts may be used by Google to improve its products, so a free key is refused. |
| 2 | Groq | `GROQ_API_KEY`, `GROQ_MODEL` | https://console.groq.com/keys | Free tier exists | No extra gate in the backend; check Groq's current data terms before sending customer drafts |
| 3 | OpenRouter | `OPENROUTER_API_KEY`, `INKLOOM_LLM_MODELS` (1-5 model ids), `INKLOOM_LLM_DATA_COLLECTION` | https://openrouter.ai/keys | `:free` models exist | **`INKLOOM_LLM_DATA_COLLECTION=deny`** (the default): only providers that don't collect prompts. Keep it `deny`. |
| 4 | Ollama (local) | `OLLAMA_MODEL`, `OLLAMA_BASE_URL` | none (install https://ollama.com) | Free | Nothing leaves the machine. **The only provider used when a brand has a `confidential` document.** |

Models must support structured (JSON) output. Model ids change; pick current ones from each
provider's model list (`services/api/.env.example` has the notes from the last check).

## Free keys: what we found on 2026-10-24

Checked live (STATUS.md, Phase 6), with the privacy defaults kept:
- **Gemini free key:** refused by the privacy rule (by design).
- **OpenRouter free key:** about 50 free requests per day without credits. One evaluation needs
  80+ calls, so it can't finish. `nvidia/nemotron-3.5-super-vl:free` refuses `deny` (it requires
  opting in to free-model training). `google/gemma-4-31b-it:free` and
  `xingchen-agi/xing4.0-29b-a4b:free` accepted the request shape but were rate-limited (429).
- **Groq:** not tried yet.
- **Ollama:** not installed on the dev machine.

So with free keys only, reviews may work some of the time (a few calls each), but a full
Scorecard evaluation will likely not finish in one day.

## Options to decide (cheapest first)

| Option | You need | Notes |
|---|---|---|
| Groq free key | Groq account, `GROQ_API_KEY` + `GROQ_MODEL` | Untested here; check data terms and rate limits |
| Local Ollama | Install Ollama, `ollama pull <model>`, set `OLLAMA_MODEL` | Free and private; slower; a cloud host won't have it (confidential documents then get the stub, nothing is sent out) |
| OpenRouter credits | About $10 credit; a paid model that accepts `deny` | Lifts the daily limit; an 80-claim run costs cents |
| Paid Gemini | A billing-enabled key, `GEMINI_PAID_TIER=true` | Gemini is tried first, so it becomes the main provider |

## Where to put them

- **Local:** `services/api/.env` (copy `.env.example`; the file is gitignored). The engine CLI reads
  only the shell environment (`services/verification/.env.example`).
- **Deployed:** the host's environment / secret settings. Never in the repo, the Dockerfile, or CI.
- **CI:** no keys. Every test is offline.
