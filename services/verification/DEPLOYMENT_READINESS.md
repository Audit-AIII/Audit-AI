# Deployment readiness (Step 8), checked 2026-10-24

**Verdict: not ready to deploy.** Nothing has been deployed. The builds and tests pass, but the
configured live model provider is refused by the privacy setting, and there's no deployment target
or credentials.

| Check | Status | Evidence |
|---|---|---|
| Frontend production build | PASS | `next build`: compiled, TypeScript clean, 17 pages |
| Backend tests | PASS | `services/api`: full pytest suite (real Postgres) |
| Engine tests and CI evaluation gates | PASS | `services/verification`: full pytest suite; `run_eval.py --check-baseline` and `--verdicts oracle --check-baseline` exit 0 |
| Backend imports with only a placeholder `DATABASE_URL` | PASS | `.github/workflows/repo-integrity.yml` step (also run locally) |
| Secrets not committed | PASS | No real-shaped key in tracked files; no `.env` tracked |
| Secrets not in frontend code | PASS | The frontend reads only `NEXT_PUBLIC_API_URL` and `NODE_ENV` |
| Required environment variables documented | PARTIAL | All three `.env.example` files exist. `BRAND_SOURCE_STORAGE_DIR` and `EVAL_DATASET_PATH` (backend settings) are missing from `services/api/.env.example` (owner: Darsh) |
| Database migrations and services documented | PASS | README "Setup and run": `docker compose up -d`, `alembic upgrade head`, `scripts/seed.py` |
| Live LLM provider configuration valid | **FAIL / BLOCKED** | The backend's only usable provider is OpenRouter `nvidia/nemotron-3.5-lightning:free`, which returns **404 "No endpoints found matching your data policy (Free model training)"** with `data_collection: deny`. Gemini has a key but no `GEMINI_MODEL` and no `GEMINI_PAID_TIER=true`, so it's off. As configured, every live review ends as "engine error" |
| Provider failures shown to users | PASS | Failed claims are `unverified` / `engine_error` with a person deciding; no provider means a labelled stub finding |
| No development mock shown as a production result | PASS | Scripted results carry model id `scripted/demo-v1` (UI: "Checked by fallback · scripted/demo-v1") and `[SEEDED]` labels; the Trust Scorecard labels scripted vs live |
| Single-process limits | KNOWN | Rate limits and idempotency replay are in memory: run one backend worker |
| Deployment target and credentials | **BLOCKED** | No hosting configuration in the repository (only a database `docker-compose.yml`); no deploy credentials available |

## Manual steps needed

1. **Choose a compliant model provider**, without relaxing `data_collection: deny`. One option:
   - a paid OpenRouter model whose endpoints pass the privacy routing. Verified answering:
     `meta-llama/llama-3.3-70b-instruct`, `google/gemini-2.5-flash-lite`,
     `mistralai/mistral-small-3.2-24b-instruct`, `openai/gpt-oss-120b`. This needs account credit
     (the account has 0).
   - or Groq (no retention of inference inputs by default) with `GROQ_API_KEY` and `GROQ_MODEL`.
   - or a paid-tier Gemini key with `GEMINI_MODEL` and `GEMINI_PAID_TIER=true`.

   Then set `INKLOOM_LLM_MODELS` (comma-separated ids, no quotes) or the provider's variables in
   the server environment.
2. **Pick a host** for the API (Python, Postgres) and the frontend (Node). Set the environment
   variables from the `.env.example` files, with `ENVIRONMENT=production` (the backend refuses to
   start with a weak `AUTH_SECRET_KEY` or `*` CORS), and `CORS_ALLOW_ORIGINS` = the frontend URL.
3. **Run `alembic upgrade head`** on the production database. Don't run the test suite against it:
   `test_migrations` empties the database.
4. **Verify the deployed app:** health endpoint, sign in, one review with a real model, and that
   the review shows the model id, not `scripted/…` or the stub.
