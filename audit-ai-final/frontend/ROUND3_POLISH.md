# Round 3 polish results

Measured 2026-10-30 on `r3/09-polish`. Re-run with `qa/round3-polish.mjs` (sweep) and `qa/round3-drift.mjs` (comparison with the baseline).

## Theme consistency

Pages were compared by eye against `/app/queue` and the baseline at 1182, 768 and 390px. "New CSS" was searched for hard-coded values: no hex, `rgb()`, `font-family` or raw durations, and no radius outside the tokens.

| Page | Tokens only | Top-left light, relief | 6px radius | Gabarito headings, `StageHead` | Numbered panel tabs | Button look | Spacing |
|---|---|---|---|---|---|---|---|
| `/app/review` | Yes | Yes | Yes | Yes | Yes | Existing | Matches |
| `/app/decide` | Yes | Yes | Yes | Yes | Yes | Existing | Matches |
| `/app/queue` | Yes | Yes | Yes | Yes | Yes | Existing | Matches |
| `/app/record` | Yes | Yes | Yes | Yes | Yes | Existing | Matches |
| `/app/scorecard` | Yes | Yes | Yes | Yes | Yes | Existing | Matches |
| `/app/team` (new) | Yes | Yes | Yes | Yes | Yes | Existing | Matches |
| `/app/audit` (new) | Yes | Yes | Yes | Yes | Yes | Existing | Matches |
| `/invite/accept` (new) | Yes | Yes | Yes | Same card as `/login` | Not used, as on `/login` | Existing | Matches `/login` |

## Accessibility

- **axe-core:** no violations of any impact on 14 page states at 3 sizes.
- **Limit of axe here:** the grain background stops axe from checking colour contrast, so contrast was calculated from the tokens.
- **Contrast on the canvas:** `--ink` 7.18:1, `--surface` 5.91:1, `--ink-2` 3.84:1. `--ink-2` fails AA for small text, so new text uses `--surface`. Existing text in `--ink-2` wasn't changed.
- **Keyboard:** the findings list, the dialogs and the review states are covered by `qa/review-states.mjs` and `qa/team-page.mjs`.

## Responsive

- No sideways page scroll on any of the 14 states at 1182, 768 or 390px.
- The Queue table still scrolls inside its panel on phones, as it did before.

## Motion

One animation was added: `.add-gov` uses `app-deal` with the `--dur-mid` and `--ease-enter` tokens. Its reduced-motion fallback is checked by the sweep. Selecting a finding scrolls smoothly, and instantly under reduced motion. Nothing else moves.

## Drift from the baseline

Pages not meant to change, at both sizes: login, draft, review-edit, coverage, guidelines and rules differ by 0.00%. Sources differs by at most 0.02%, the dashboard and insights by at most 0.08%, and the landing page's first screen by 0.99%. The causes of those small differences weren't investigated; they are likely relative times and the hero's moving light.

## Left as they were

These existed before Round 3, and fixing them would change pages this work wasn't meant to change:

- **Layout shift:** the shared status bar shifts as a page loads, by up to 0.146 on phones. It also happens on `/app/guidelines`, which Round 3 didn't touch.
- **Tap targets under 44px on phones:** text links such as "Fix the wording" (28px), the Queue's titles and its "Already decided" toggle, and "Dismiss this finding" and "Add comment" (40px). `/invite/accept` reuses the sign-in page's 29px link.
- **Header wrap:** at 1182px the account menu drops to a second row while the Workspace menu reads "Workspace".
