# Performance baseline (before any fix)

Measured 2026-10-29 on branch `perf/optimise` from `main` at `ebb4c12` (frontend identical to `0bda78f`), against a local production build
(`npm run build && npm start`, Next 16.4.2 Turbopack). No Vercel URL was given, so the deployed
site was not measured. Raw data: `qa/out/perf-baseline.json` (git-ignored); scripts are in `qa/`.

## How it was measured

- `qa/perf-r3.mjs`: Playwright Chromium (headless), cold cache, median of 3 loads per route.
  - **Mobile profile:** 412×823 at 1.75×, CPU 4× slower, 150 ms RTT / 1.6 Mbps (Lighthouse's
    mobile throttling).
  - **Desktop profile:** 1350×940, no throttling.
  - **Scroll test:** a scripted wheel scroll of `/` from top to bottom, while recording frame times
    (rAF), long tasks and a DevTools timeline trace.
  - **Navigation:** `/`→`/login` (plain client navigation) and `/`→`/app` (sand-wave), on desktop.
- `qa/perf-paint.mjs`: counts Paint events per DOM node, while idle and while scrolling.
- `qa/perf-shots.mjs`: before/after screenshots at 1182×937 and 390×844, animations frozen at a
  fixed time. A repeat run diffs at 0 (one frame 0.1%).
- `/app/*` pages are measured signed in (session in localStorage) with **no backend**. The backend
  needs Docker/PostgreSQL, which isn't running here. This is also what a Vercel deployment with an
  unreachable API sees.
- **Not run:** Lighthouse is not installed in the project and the rules say to ask before adding
  tools. The metrics above are collected with the same browser APIs Lighthouse uses (LCP, CLS,
  long tasks). TBT here = sum of (long task − 50 ms) after FCP. INP needs a real interaction and
  is not measured. Bundle analyzer not used (needs approval): sizes come from `.next` output and
  network transfer.
- Headless Chromium rasterises on the CPU (no GPU), so paint/raster milliseconds are higher than
  on a real phone. Use them to compare runs, not as absolute phone numbers.

## Load (median of 3)

| Profile | Route | FCP | LCP | CLS | TBT | JS (gz) | CSS | Fonts | Requests |
|---|---|---|---|---|---|---|---|---|---|
| mobile | `/` | 1024 ms | 1024 ms | 0.001 | 73 ms | 205 kB | 23 kB | 76 kB | 18 |
| mobile | `/login` | 608 ms | 2012 ms | **0.057** | 63 ms | 205 kB | 23 kB | 63 kB | 15 |
| mobile | `/app/sources` | 596 ms | 2092 ms | 0 | 184 ms | 275 kB | 27 kB | 63 kB | 48 |
| mobile | `/app/review` | 600 ms | 2128 ms | 0 | 215 ms | 275 kB | 27 kB | 63 kB | 47 |
| desktop | `/` | 220 ms | 220 ms | 0.005 | 0 | 205 kB | 23 kB | 76 kB | 18 |
| desktop | `/login` | 76 ms | 100 ms | 0.012 | 0 | 205 kB | 23 kB | 63 kB | 15 |
| desktop | `/app/sources` | 56 ms | 172 ms | 0 | 0 | 275 kB | 27 kB | 63 kB | 48 |
| desktop | `/app/review` | 48 ms | 152 ms | 0 | 0 | 275 kB | 27 kB | 63 kB | 47 |

On mobile, LCP on `/login` and `/app` lands about 1.4 s after FCP. That is the heading being
repainted once the web font arrives: fonts are only discovered after the CSS has loaded (no
preload). The 0.057 CLS on `/login` comes from the same font swap.

## Scroll and idle on `/`

| | Mobile | Desktop |
|---|---|---|
| Scroll: average fps (rAF) | 56 | 59 |
| Scroll: dropped frames | 48 | 15 |
| Scroll: worst frame | 67 ms | 50 ms |
| Scroll: long tasks > 50 ms | 0 | 0 |
| Scroll: raster time (trace) | 3622 ms | **6825 ms** |
| Scroll: paint time | 3001 ms | 492 ms |
| Scroll: Paint events | 2056 | 2973 |
| **Idle 3 s:** Paint events | **2315** | **2314** |
| **Idle 3 s:** raster time | 660 ms | **1459 ms** |

The main thread keeps up (no long tasks, ~56–59 fps). The cost is in **paint and raster**: on a
real phone that becomes the stutter and the hot, slow feel. The mobile scroll did not reach the
bottom in the time allowed; the same script is used before and after.

## Navigation

| | Time |
|---|---|
| `/` → `/login` (client navigation, heading visible) | 108 ms |
| `/` → `/app` sand-wave: **navigation starts** | **816 ms** |
| `/` → `/app` sand-wave: transition finished | 1933 ms (55 fps, 10 dropped frames) |

## API with no answer (`/app/sources`, signed in)

| Backend state | Error shown after |
|---|---|
| Connection refused (nothing on `localhost:8000`) | ~0.1 s (fine) |
| Host accepts but **never answers** | **never** (still loading after 40 s) |

## Bundle (from `.next`, gzipped)

| Chunk | Size | Where it loads |
|---|---|---|
| React + Next runtime (3 chunks) | ~156 kB | every route |
| GSAP core | 27 kB | **every route** (the sand-wave in the root layout imports it) |
| ScrollTrigger + Lenis | 28 kB | `/` only |
| Polyfills (`nomodule`) | 39 kB | old browsers only, never downloaded by modern ones |
| CSS (one file for all routes) | 23 kB | every route |
| Fonts: Gabarito + Instrument Sans latin (+ Gabarito latin-ext on `/`) | 63–76 kB | every route, **not preloaded** |

All 16 routes are prerendered as static HTML. No images ship apart from a 26 kB favicon.

## Suspects A–I: what the measurements say

**Attribution method.** Overrides were injected into the live page and the same trace re-run
(`qa/out/attrib*.mjs`). Each row is one override; desktop, `/`.

| Override | Scroll raster | Idle raster | Idle paints |
|---|---|---|---|
| none (baseline) | 9677 ms | 1477 ms | 2340 |
| **grain tokens → none** | **968 ms (−90%)** | | |
| relief filter off | 8493 ms (−12%) | 1442 ms (−2%) | |
| drop-shadow filters off | 9236 ms (−5%) | | |
| soft-light blend off | 8865 ms (−8%) | 1484 ms (0%) | |
| all box-shadows off | 8638 ms (−11%) | | |
| all text-shadows off | 9133 ms (−6%) | | |
| `.sources` tide-drift paused | 8818 ms (−9%) | 1336 ms (−10%) | **1190 (−49%)** |
| **hero word sway paused** | | **0 ms (−100%)** | 1246 |

- **A. Live SVG relief filters: confirmed, minor.**
  - `#cut-relief` sits on 7 kinds of heading (hero, statement, contact, login, stage titles).
  - Turning it off saves 12% of scroll raster and 2% of idle raster. It is not the main cost.
- **B. Paper grain: confirmed, the main cause.**
  - `--grain*` are SVG data-URIs with 3–6 `feTurbulence` layers each.
  - They are used by 48 rules, including the full-page `.board`, every card and the hero.
  - Chromium keeps SVG backgrounds as vector recordings and **re-runs the turbulence filters every
    time a tile is rastered**. That is 90% of scroll raster.
  - There is no `background-attachment: fixed` and there are no full-viewport fixed grain layers.
- **C. Paint-heavy effects: confirmed, small.**
  - Two infinite animations repaint on the main thread:
    - The hero words' `text-shadow` sway (16 s, `infinite alternate`): **all** the idle raster.
    - `tide-drift`, which animates `mask-position` on every `.sources__row` pseudo-element: it
      repaints the root layer every frame while far off-screen, and doubles the idle paint count.
  - Hover-only `box-shadow` transitions and the scrubbed `--lift` drop-shadow on the seal are
    short and local.
  - Everything else animated is `transform`/`opacity`/`translate`.
- **D. Scroll engine: mostly rejected.**
  - Seven ScrollTriggers on `/`. Lenis and ScrollTrigger load and run only on `/`, not on `/app`.
  - `ScrollTrigger.refresh()` is called once (Process.tsx), not repeatedly.
  - Both pointer loops stop themselves once the light settles, and only run on fine pointers.
  - The hero sway and light already pause while the hero is scrolled away (`data-sinking`).
  - No long tasks during scroll.
- **E. Sand-wave: confirmed, by design.**
  - `router.push` is only called after the 0.8 s cover animation, so navigation starts at 816 ms.
  - It animates `transform` on one layer, but that layer carries a `drop-shadow` filter and the
    `#shell-sand` turbulence filter.
- **F. Bundle and loading: partly confirmed.**
  - GSAP core ships on every route.
  - Fonts are not preloaded (late LCP and the CLS on mobile `/login`).
  - Landing-only libraries do **not** load on `/app`.
  - Metric-matched fallback fonts already exist (`base.css`).
- **G. Images/assets: rejected.** There are none apart from the favicon.
- **H. API loading: confirmed for an unreachable-but-accepting host.**
  - No request has a timeout, so a hung backend keeps every `/app` page loading forever.
  - `retryWhileInFlight` only retries 409 "still being processed" on requests with an
    Idempotency-Key, so it does **not** cause the 1.5–12 s waits on plain reads.
  - This build has `NEXT_PUBLIC_API_URL` unset, so it calls `http://localhost:8000`. Whether the
    Vercel build does too depends on the project's env vars, which can't be seen from here (see
    PERF_RESULT.md).
- **I. Next/Vercel config: rejected.**
  - Every route is static, with no `force-dynamic` and no large props.
  - `devIndicators: false` only affects `next dev`.
  - Compression and immutable caching of `/_next/static` come from Next/Vercel by default.
