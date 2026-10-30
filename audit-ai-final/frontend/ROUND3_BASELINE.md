# Round 3 frontend baseline

Captured 2026-10-30 on `r3/00-baseline`, from `main` at `ec484f1`, before any Round 3 frontend change. This is the "before" state that later phases compare against.

## How this was captured

- Backend: `services/api` against Docker Postgres on port 5433, migration `0016` (head), after `scripts/seed.py --reset`.
- Frontend: `npm run dev`.
- Signed in as `asha@seed.inkloom.demo`. Seeded reviews use the offline scripted provider, so no AI provider was called.
- Script: `AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/round3-baseline.mjs`.
- Screenshots: `.round3-baseline/<route>-desktop.png` (1182x937) and `<route>-mobile.png` (390x844). Full page, except the landing page, which is viewport only. The folder is git-ignored, along with `routes.json`, the raw record of each visit.

## Routes

All 15 routes loaded at both sizes with no uncaught page errors and no horizontal scroll. "Works" means it loaded and showed seed data. It does not mean every action on the page was exercised.

| Route | Main files | API calls on load (all also call `GET /api/auth/me` except `/` and `/login`) | Result |
|---|---|---|---|
| `/` | `app/page.tsx`, `components/sections/*` | None | Works |
| `/login` | `app/login/LoginForm.tsx` | None | Works |
| `/app` | `app/app/page.tsx` | Redirects to `/app/insights` | Works |
| `/app/sources` | `app/app/sources/BrandSources.tsx` | `GET /api/brands`, `GET /api/brands/{id}/sources` | Works |
| `/app/draft` | `app/app/draft/` | `GET /api/brands` | Works |
| `/app/review?id=` | `app/app/review/ReviewResult.tsx` | `GET /api/reviews/{id}`, `GET /api/findings/{id}/comments` | Works |
| `/app/review-edit?id=` | `app/app/review-edit/Editor.tsx` | `GET /api/reviews/{id}`, `GET /api/content/{id}/history` | Works |
| `/app/coverage?id=` | `app/app/coverage/Coverage.tsx` | `GET /api/reviews/{id}` | Works |
| `/app/decide?id=` | `app/app/decide/DecidePanel.tsx` | `GET /api/reviews/{id}`, `GET /api/content/{id}/history` | Works |
| `/app/record?id=` | `app/app/record/RecordPanel.tsx` | `GET /api/reviews/{id}` | Works |
| `/app/queue` | `app/app/queue/Queue.tsx` | `GET /api/brands`, `GET /api/reviews` | Works |
| `/app/guidelines` | `app/app/guidelines/` | `GET /api/brands`, `GET /api/brands/{id}/sources` | Works |
| `/app/rules` | `app/app/rules/` | `GET /api/brands`, `GET /api/brands/{id}/rules` | Works |
| `/app/insights` | `app/app/insights/` | `GET /api/brands`, `GET /api/brands/{id}/sources`, `GET /api/reviews`, `GET /api/analytics/brand-risk` | Works; its heading is "Dashboard" |
| `/app/scorecard` | `app/app/scorecard/Scorecard.tsx`, `RunReport.tsx` | `GET /api/evaluations/latest` | Works; the API returns 404 because no run exists, and the browser logs that 404 as a console error |

## Existing issues found

These are not fixed here, and Phase 0 changes no product code.

- **Header wrap:** on `/app/review` at 1182px the account menu drops to a second header row. `/app/queue` fits on one row at the same size. The cause hasn't been investigated.
- **Single-user wording:** these lines stop being true in a team workspace, so Phases 2 and 3 need to handle them:
  - Decide: "You decide on your own content."
  - Review: "Only you can see these." (comments)
- **Old QA script:** `qa/single-user-walk.mjs` fails on any role, approver or reviewer wording. It assumes the personal workspace, so it needs revisiting once governance wording ships.
- **Seed coverage:** Asha's seeded findings are all `check_type: retrieval`. Rule findings, the `tone` count and failed or incomplete reviews can't be seen from her seed data alone, so later phases have to create or route those states.

## Check results

| Check | Result |
|---|---|
| `npx tsc --noEmit` | Pass |
| `npm run lint` | Pass, no output |
| `npm run build` | Pass, 16 routes including `/_not-found` |
| `qa/unit/*.test.mts` | All 7 files pass: additions-coverage, additions-diff, codepoints, dashboard, evaluation-run, finding-state, locks |
