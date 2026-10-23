# Wiring the new pages (proposals only: none of these are applied)

The new pages are reachable by direct URL only. Each item below is a single change you could
approve on its own. Line numbers are from the commit that added this file; check them again
before applying.

| Page | URL |
|---|---|
| Guidelines | `/app/guidelines` |
| Correction editor | `/app/review-edit?id=<review id>` |
| Evidence coverage | `/app/coverage?id=<review id>` |
| Review queue | `/app/queue` |
| Insights | `/app/insights` |
| Trust Scorecard | `/app/scorecard` |

## Guidelines

1. **Link from Sources (Panel 3, under "Next: check a draft").**
   `app/app/sources/BrandSources.tsx`, after line 273, add:
   ```tsx
   <a className="link" href="/app/guidelines">Manage versions and withdrawals →</a>
   ```

2. **Optional: a sixth item in the stage bar.** Not recommended: it changes the five-stage bar
   on every page. `components/app/stages.ts`, after the `sources` entry (line 3), add:
   ```ts
   { slug: "guidelines", n: "01b", label: "Guidelines", hint: "Upload, update or withdraw the documents drafts are checked against." },
   ```

## Correction editor

3. **Link from the Review page, next to "Choose what to do".**
   `app/app/review/ReviewResult.tsx`, before the line with `Choose what to do →` (line 204), add:
   ```tsx
   <a className="link" href={`/app/review-edit?id=${review.id}`}>Fix the wording →</a>
   ```

Note: `components/app/AppShell.tsx` matches the stage bar with `pathname.startsWith("/app/review")`,
so `/app/review-edit` already highlights "Review" in the stage bar. Harmless; no change proposed.

## Evidence coverage

4. **Link from the Review page, beside the legend in "Your draft".**
   `app/app/review/ReviewResult.tsx`, at the same place as item 3 (before line 204), add:
   ```tsx
   <a className="link" href={`/app/coverage?id=${review.id}`}>See evidence coverage →</a>
   ```

## Review queue

5. **Link from the Decide page's empty state ("No review chosen").**
   `app/app/decide/DecidePanel.tsx`, line 52, inside `Empty`, after the existing
   `<Button href="/app/draft">Check a draft →</Button>`, add:
   ```tsx
   <a className="link" href="/app/queue">Open the review queue →</a>
   ```

## Insights and Trust Scorecard

**Trust Scorecard data (EVAL.md Phase 8):**
- **Data:** `/app/scorecard` reads `GET /api/evaluations/latest` (now on the backend, any signed-in
  member) through `latestEvaluation()` in `lib/additions/analytics.ts`. The response follows
  contract `evaluation-summary-v1` (`services/verification/schemas/evaluation_summary.schema.json`)
  and is checked by `parseEvaluation()`; a mismatch is shown as an error, never as data.
- **No calculations here:** the page computes no metric. Metric values are the engine's own
  `display` strings.
- **States:** no report yet, an incomplete newest run, a stale report, and a backend without the
  route.
- **Removed:** the old "Run evaluation" button and the sample numbers. There is no `POST` endpoint
  (runs can cost money and take minutes), and real results now exist.

6. **Links in the account menu (signed in), next to "Sign out".**
   `components/layout/AccountNav.tsx`, line 66, after `<p className="account__menu-email">{session.email}</p>`, add:
   ```tsx
   <a className="link" href="/app/queue">Review queue</a> <a className="link" href="/app/insights">Insights</a> <a className="link" href="/app/scorecard">Trust Scorecard</a>
   ```
   (This menu also shows on the landing page, so these links would appear there too.)
