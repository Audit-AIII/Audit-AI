# End-to-end journeys

These drive the real pages against the real backend. Only journey 11 blocks the API, to see a network failure. No live AI key is needed, and the runner refuses to start if the server has one, so a run can't spend provider quota.

## Run them

1. Start Postgres and reseed. From `services/api`:

   ```sh
   .venv/Scripts/python scripts/seed.py --reset
   ```

2. Start the API with no AI keys and the rate limits raised for test accounts. Empty values override `.env`:

   ```sh
   GEMINI_API_KEY= GROQ_API_KEY= OPENROUTER_API_KEY= OLLAMA_MODEL= OLLAMA_BASE_URL= INKLOOM_LLM_MODELS= \
   RATE_LIMIT_REGISTRATIONS_PER_IP=1000 RATE_LIMIT_SUBMISSIONS_PER_USER=1000 RATE_LIMIT_SUBMISSIONS_PER_ORGANISATION=1000 \
   .venv/Scripts/python -m uvicorn inkloom_api.main:app --port 8000
   ```

3. Start the frontend from `audit-ai-final/frontend` with `npm run dev`.

4. Run everything, or name journeys by number:

   ```sh
   AUDIT_PASSWORD='<DEMO_PASSWORD from scripts/seed.py>' npm run e2e
   AUDIT_PASSWORD='<DEMO_PASSWORD from scripts/seed.py>' npm run e2e -- 04 06
   ```

Screenshots of failures go to `qa/out/e2e/`. Journeys 06 and 08 use the team journey 04 creates, so run 04 with them.

## What they leave behind

Runs add throwaway `e2e-*@example.com` accounts to the local database, and journeys 01, 02 and 09 add to the seeded demo accounts. `seed.py --reset` restores the demo accounts, but not the throwaway ones. Never run this against a real database.

## Journeys

| # | Covers |
|---|---|
| 01 | Upload a draft, placeholder labelling, server counts and a full finding card |
| 02 | Safer wording label, new version, old version can't be approved |
| 03 | Solo send back, approve, and a stale version refused with the note kept |
| 04 | A team invited through the pages, from writer to published, with buttons matching `allowed_actions` at each step |
| 05 | Self-approval refused with the reason shown and recorded |
| 06 | Draft history and the owners-only audit log |
| 07 | Revoked and wrong-email links, role change, removal, last owner rule |
| 08 | Workspace switch keeps data apart |
| 09 | Dismiss, restore, comment, Intent-lock |
| 10 | Scorecard with no stored run (the published benchmark), and with no provider |
| 11 | Network failure and recovery; empty review if the seed has one |
| 12 | Phone width on each core page |
| 13 | Skipped until the API sends tone findings |
| 14 | Documents (upload, new version, withdraw), brand rules, the editor's re-check, and Coverage |

`services/api/scripts/check_endpoints.py` calls every API route, and `qa/route-crawl.mjs` opens every page and link. Run both with the same setup.

Not covered here, because they need an AI provider: a stored evaluation run and real AI findings on a new draft. `qa/scorecard-states.mjs` covers the page's handling of a stored run, using the API's documented example.
