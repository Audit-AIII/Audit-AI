# Phase 5: Provider adapter, cache, idempotency, rate limits

Read `00_CONTEXT.md` first. Requires Phase 4.

## Goal
LLM calls are reliable on free tiers, never leak confidential sources, and never create duplicate work.

## Tasks
1. Build a small provider interface so the engine never holds API keys. Implement providers in this order: Google Gemini Flash (Google AI Studio free key), Groq (Llama 3.3 70B, Llama 4 or gpt-oss), OpenRouter `:free` models, local Ollama.
2. Read provider and model from environment or config. Never hard-code a model name. Free tiers change often.
3. Fixed timeout per call. Retry only 429, 5xx and timeouts, a bounded number of times, then fall through to the next provider. Invalid JSON or schema from a provider counts as a provider failure.
4. If every provider fails, set the review to `failed` with a safe error code and request ID. Never approved.
5. Result cache keyed by content hash + source version + engine config + organisation ID. The organisation ID is mandatory so tenants never share cache entries.
6. Idempotency keys on `POST /api/reviews` and `rerun`: a duplicate returns the first job and makes no second LLM call.
7. Rate limits per user and per organisation on submissions.
8. Confidential routing: if any source in the review is `confidential`, never call a cloud provider; use Ollama or rules-only checks.
9. Log every external call (provider, model, review ID, timestamp) to `external_call_log`. Do not log full content, credentials or raw provider errors.
10. Store provider, model ID and prompt version on each review (engine config).
11. Keep keys in environment variables only. Update `.env.example` and `DISCLOSURE.md`.

## Wiring with teammates
Member 2's engine should call this adapter, not a provider SDK directly. Agree the interface with them and do not edit their code without asking.

## Tests (write now)
- Provider returns 429: adapter falls back; review completes or fails safely.
- Timeout: bounded retry then fallback; never approved.
- Invalid JSON: treated as failure.
- All providers down: review is `failed`.
- Duplicate idempotency key: one job, one LLM call.
- Same content in two organisations: separate cache entries.
- Confidential source: external call log stays empty.

## Done when
All seven tests pass with mocked providers, and a real review works with a free Gemini key using synthetic content only.

## Paste into Claude Code
> Read 00_CONTEXT.md and this file. Build the provider interface and the failure behaviour with mocks first, then cache, idempotency and rate limits. Show me after each.
