# DESIGN.md — "Pressed Paper" design system for **Audit AI** (visual style modelled on relevovinco.com)

> Purpose: let an AI coding agent build **Audit AI** (landing page + review workspace) with the **look, feel, motion and micro-interactions** of relevovinco.com. Part A = visual system, Part B (§15+) = Audit AI product UI.
> Source of truth order: **this file → `tokens.css` → `reference/screenshots/*` → live site (inspection)**.
> Do **not** use the original DesignMD `design.md` shadows — they are truncated mid-value. This file contains the repaired versions.

Confidence tags used everywhere:
- **[M]** measured by the scan — use exactly.
- **[R]** reconstructed from partial values + screenshots — implement, then calibrate against the screenshots.
- **[I]** inferred from selectors/behaviour — verify on the live site before trusting.

---

## 0. Project brief — Audit AI

```
PROJECT NAME:     Audit AI   (hackathon problem statement: Inkloom AI "brand governance"; team CodeNinjas)
ONE-LINE:         An intelligent brand-governance platform that reviews content BEFORE publication and checks it
                  against approved guidelines, facts and assets — explaining every finding and suggesting fixes
                  that keep the creator's purpose, with humans making the final call.
AUDIENCE:         Creators (employees, agencies, AI tools) · Brand managers · Authorised reviewers (legal/compliance) · Admins
PRIMARY CTA:      "Start a review"
SECONDARY CTA:    "See a sample finding"
DESIGN INTENT:    Calm, tactile, trustworthy. Warm "pressed paper" UI so an audit tool feels human, not punitive.
CORE PRINCIPLE:   Missing evidence means "unverified", never "false". Automation proposes; people decide.
FRONTEND OWNER:   Chahit (review UI, audit trail). Single owner of ./frontend — no shared files with other roles.
STACK (per team deck): Next.js + TypeScript (+ PostgreSQL/pgvector, LLM API, private object storage on the backend)
                  Frontend add-ons: see §20.
SCOPE OF THIS FILE: Part A (§1–§14) = visual system. Part B (§15–§22) = Audit AI product UI, copy, data contracts, priorities.
```

### 0.1 Translating the metaphor — the six finishes become the six checks
Audit AI detects issues in **tone, terminology, messaging/facts, claims, visual consistency, accessibility** — exactly six, so they replace the six packaging finishes one-for-one on the landing page *and* become the icon/visual language for check categories inside the app.

| Original finish (visual recipe §6) | Audit AI check | Why it fits |
|---|---|---|
| Burnish (soft bloom) §6.8 | **Tone** | Voice is warmth/intensity, not an edge |
| Texture plate (ribs) §6.7 | **Terminology** | Repeated words form a pattern; deviations break the ribs |
| Die-cut window (dark hole) §6.5 | **Facts & messaging** | The window shows the approved source behind the claim |
| Blind emboss (raised disc) §6.3 | **Claims** | A raised assertion that must be supported |
| Score & fold §6.6 | **Visual consistency** | Image vs approved palette/logo, two halves compared |
| Deboss (pressed ring) §6.4 | **Accessibility** | A pressed ring doubles as the focus/contrast motif |

Relief semantics for the whole app (rule 3 of §1):
- **Raised** = approved / supported / available action.
- **Pressed** = contradicted / needs attention / user input.
- **Die-cut (dark window)** = evidence — the source excerpt that justifies a finding is always shown in a window.
- **Flat + dashed outline** = unverified (no evidence found).

### 0.2 Do not copy · hackathon disclosure
Replicate structure, tokens, motion and craft only. Do not reuse the original studio's brand name, logo, copy or photos. The Inkloom rules (#6, #7, "Submission Integrity") require disclosure of templates/reused material and significant AI assistance, so add to the README and submission: *"UI visual system modelled on the public style of relevovinco.com (tokens/effects re-implemented from scratch; no code, copy or images copied); frontend code generated with Claude Code and reviewed by the team."* Also note rule #1: **design/planning now is fine; write the product code inside the official build window** and keep commit history clean.

### 0.3 Naming
The plan PDF uses the organiser's name "InkLoom" for the product and "InkWatch / InkInsight" for features. In the UI use **Audit AI** everywhere; rename features to **Source Watch** (drift re-flagging) and **Insights** (guideline health). Keep **Trust Scorecard**, **Intent-lock**, **Data Passport**, **Evidence coverage** — those are the "three named improvements" (Source Watch, Trust Scorecard, Intent-lock) judges will look for, so use exactly those labels in nav, headings and the demo.

---

## 1. Design DNA — the 6 rules

1. **One material.** Everything is the same warm cardboard (`#d4b08f`). Hierarchy comes from *relief*, never from extra hues.
2. **One light source: top-left.** Raised things get a bright rim on their top-left edge and a soft shadow falling bottom-right. Pressed things get a dark inner shadow top-left and a bright rim bottom-right. Never mix directions.
3. **Two states of matter:** raised (`--shadow-raised*`) and pressed (`--shadow-well`, `--shadow-window`). Interaction = moving from raised toward pressed.
4. **Restraint.** No gradients on UI, no bounce/spring, no extra accent colours. Orange `#d98c59` exists only inside imagery. *Single exception:* the low-saturation evidence-status colours in §16, used only inside the app.
5. **Big condensed-feeling display type, tiny quiet body.** Gabarito 700 uppercase headings at 64–133px next to 17px Instrument Sans.
6. **Paper grain everywhere.** A fine two-tone speckle sits on the canvas and on the dark bands; flat fills look wrong.

---

## 2. Colour tokens

| Token | Hex | Role |
|---|---|---|
| `--canvas` | `#d4b08f` [M] | Page paper, cards, buttons |
| `--ink` | `#36261a` [M] | Primary text, labels, rules (7.2:1 on canvas) |
| `--ink-2` | `#6b4c34` [M] | Secondary copy, **debossed headline fill**, flute lines (3.8:1 — large text / non-essential only) |
| `--accent` | `#8c5940` [M] | Focus ring, rare fills (0.3% of page — keep it rare) |
| `--surface` | `#47331f` [M] | Dark wells, hero "STAND OUT" label boxes, the Studio band |
| `--gray-mid` `--gray-light` | `#c0a68c` `#d9c0a6` [M] | Fold panel, subtle fills |
| `--orange-mid` | `#d98c59` [M] | Imagery/burnish only |
| `--deep` | `#1f140b` [M] | Shadow colour, hero wash |
| `--deep-orange` | `#40260c` [M] | Dark inner panels |
| `--paper-hi` | `#f7e8d2` [R] | The highlight in every light rim (from `color(srgb .9686 .9098 .8235)`) |
| `--light-glow` | `#7b5b41` [R] | Centre of the moving hero light |

On `--surface` bands: text = `--canvas`; secondary text = `--gray-light`; headlines get `--text-raised`.
Contrast warning: 74% of original text passes AA. Body text must be `--ink`, never `--ink-2`, on canvas.

---

## 3. Typography

**Fonts (both free, Google Fonts / OFL — self-host):**
- Display: **Gabarito** 700 only (+600 optional).
- Body/UI: **Instrument Sans** 400 and 600 (700 for the H1-level sample only).
- Use `font-display: swap`, ship only the weights above, add metric-matched fallbacks (`size-adjust`) to avoid layout shift.

| Role | Size | Line-height | Tracking | Weight | Family | Notes |
|---|---|---|---|---|---|---|
| display | 133px | .92 | 1.32px | 700 | Gabarito | Hero words. Fluid: `clamp(52px, 11.25vw, 133px)` [R] |
| heading-xl | 124px | .96 | 1.23px | 700 | Gabarito | Dark "craft" band words |
| heading-lg | 64px | .92 | .64px | 700 | Gabarito | Section H2s (4 lines max) |
| heading | 40px | 1.1 | .8px | 700 | Gabarito | |
| heading-sm | 31–33px | 1.01–1.1 | .31px | 700 | Gabarito | Pull-quote |
| subheading / h3 | 22–23px | 1.05 | .45px | 700 | Gabarito | Card titles |
| body | 18px | 1.55 | — | 400 | Instrument | Hero paragraph |
| body-long | 17px | 26px | — | 400 | Instrument | Section copy |
| small / button | 16px | 1.2 | .15px | 600 | Instrument | Buttons |
| nav / link | 15px | 23px | — | 600 | Instrument | |
| caption | 13px | 1.35 | 1.04px | 600 | Instrument | UPPERCASE labels (FINISH / BOARD / RUN) |

**Case rule [M + screenshots]:** headings are *written in sentence case* in the DOM but **rendered uppercase** with `text-transform: uppercase` (H2, H3, logo, captions, pull-quote, attribution). Body copy stays sentence case. Headline words wrap naturally to 3–4 short lines (use `text-wrap: balance`).
Hero headline = 4 lines across two treatments (§7.1). H1 sits at Gabarito; the scan's "Instrument Sans 34px H1" is a visually-hidden/SEO artefact — ignore.

---

## 4. Spacing, grid, radii

- Base unit **2px**. Card padding in the scan (5px) is an artefact — real card padding: 26px 26px 22px for step cards, 20px 18px for work sleeves, 0 for swatches.
- Container: `max-width: 1160px`; gutter `--gutter = clamp(20px, 6.5vw, 96px)` (=77px at 1182) → inner content ≈ 1013px. [M]
- Section padding: `clamp(96px, 15vh, 180px)` top/bottom (=141px at 937h) [M].
- Grid gap 47px; list gap 12px; head grids `1fr 1fr` aligned `end`; hero grid `2fr 1fr`.
- Radii: **6px for everything UI and images**; 2px tags; dark studio panel `clamp(18px, 2.4vw, 34px)`; circles 50%. The scan's "pill 9999px" advice is a generic template line — **do not use pills**.
- Z-index only: `1` (under-decor), `3` (decor/wash/rims), `50` (header).

---

## 5. Elevation (calibrated) — see `tokens.css`

> **Calibrated 2026-10-22** with Playwright against the live site at 1182×937 (raw data: `design/probe.json`). Values below are now **[M]**. `paper` = `rgb(247 232 210)`, `deep` = `rgb(31 20 11)`.

| Token | Use | Value |
|---|---|---|
| `--shadow-raised` (= `--shadow-raised-sm`) | buttons, cards, swatches, sleeves, step cards — **one recipe for all** | `-1px -1px 0 paper/.8, 1px 1px 0 deep/.22, 3px 5px 6px deep/.2, 12px 18px 28px deep/.26` |
| `--shadow-press` | button / icon-button hover + active | same 4 layers collapsed: `0 0 0 paper/.8, 0 0 0 deep/.22, 1px 1px 1px deep/.2, 2px 3px 5px deep/.26` |
| `--shadow-well` | fields, deboss rings, button `::after` overlay, FAQ creases | `inset 4px 6px 10px deep/.38, inset 1px 1px 2px deep/.35, inset -1px -1px 0 paper/.85` |
| `--shadow-window` | die-cut dark boxes (hero label boxes, contact label box, evidence) | `inset 7px 10px 16px deep/.72, inset 2px 2px 3px deep/.55, 1px 1px 0 paper/.85, -1px -1px 0 deep/.25` |
| `--shadow-sheet` | fixed nav bar | `0 1px 0 paper/.7, 0 8px 18px deep/.28` |
| `--shadow-flap` | paper sheet sliding over a dark layer (statement band) | `inset 0 1px 0 paper/.75, 0 -2px 6px deep/.22, 0 -16px 40px deep/.42` |
| `--shadow-lift` | single soft drop | `10px 16px 18px deep/.32` |

Text relief [M]: `--text-raised` (on dark), `--text-raised-b` (sway end state), `--text-raised-canvas` (FAQ questions, prices, pressed statement lines), `--text-pressed` / `--text-pressed-b`, `--text-etched` (h3 and wordmark: `1px 1px 0 paper/.75`). **Pressed headings also need an inner-shadow SVG filter** (`filter: url(#cut-relief)`: inverted alpha → offset 3.5/4.5px → blur 2 → flood `--deep` → clip to glyph). Text-shadow alone looks flat.

---

## 6. Texture & effect recipes (CSS)

```css
/* 6.1 Paper grain (canvas + dark bands) [M technique] — SVG fractal-noise data URL (--grain in tokens.css):
       fine dark tooth + sparse dark specks + sparse light specks. Own filter values, re-implemented. */

/* 6.2 Raised card / swatch */
.card { background: var(--canvas); border-radius: var(--r-ui); box-shadow: var(--shadow-raised); }

/* 6.3 Blind emboss (raised disc) */
.emboss { width: 46%; aspect-ratio: 1; border-radius: 50%; background: var(--canvas);
  box-shadow: var(--rim-hi), 6px 9px 14px rgb(31 20 11 / .35); }

/* 6.4 Deboss (pressed ring) */
.deboss { width: 46%; aspect-ratio: 1; border-radius: 50%; background: transparent; box-shadow: var(--shadow-well); }

/* 6.5 Die-cut window (dark hole) */
.window { background: var(--surface); border-radius: var(--r-ui); box-shadow: var(--shadow-window); }
/* variant: a photo sits behind and shows through a circular/rect hole (work cards) */

/* 6.6 Score & fold: left half canvas, right half --gray-mid with a 1px dark crease + inner shadow */
.fold { background: linear-gradient(90deg, var(--canvas) 50%, var(--gray-mid) 50%);
  box-shadow: inset 8px 0 10px -6px rgb(31 20 11 / .35); }

/* 6.7 Texture plate: recessed rectangle filled with vertical ribs */
.plate { box-shadow: var(--shadow-well); background:
  repeating-linear-gradient(90deg, rgb(31 20 11 / .22) 0 1px, transparent 1px 7px); }

/* 6.8 Burnish: soft dark radial bloom, no edge */
.burnish { border-radius: 50%; background: radial-gradient(closest-side, #7b5b41, rgb(123 91 65 / 0)); filter: blur(2px); }

/* 6.9 Pressed (debossed) headline — fill ink-2 + inner-shadow filter [M] */
.h-pressed { color: var(--ink-2); text-shadow: var(--text-pressed); filter: url(#cut-relief); text-transform: uppercase; }
/* 6.10 Raised headline on dark — fill canvas */
.h-raised  { color: var(--canvas); text-shadow: var(--text-raised); text-transform: uppercase; }

/* 6.11 Dotted spec table (FINISH / BOARD / RUN) */
.spec-row { display: grid; grid-template-columns: 96px 1fr; padding: 8px 0; border-top: 1px dotted var(--ink-2); }
.spec-row dt { font: 600 13px/1.35 var(--font-body); letter-spacing: 1.04px; text-transform: uppercase; }

/* 6.12 Rules between list rows: 1px solid, --ink-2 at ~70% */
/* 6.13 Cross-section diagrams: two thin raised bars (top/bottom liner) + a flute wave in --ink-2 (inline SVG, stroke 2px, round caps) or vertical 1px lines for honeycomb */
/* 6.14 Punch disc: 296px circle, 1px rim + faint raised edge, with a 118px deboss hole centred */
```

---

## 7. Animation & motion

**Library stack (measured):** Lenis (smooth scroll) + GSAP ScrollTrigger. Scroll is virtualised → give ScrollTrigger Lenis' proxy (`lenis.on('scroll', ScrollTrigger.update)` and `gsap.ticker.add(t => lenis.raf(t*1000))`, `gsap.ticker.lagSmoothing(0)`).

### 7.1 Hero (on load) [M keyframe, I for wiring]
Layout (1182×937): fixed header; word group 1 **"STAND OUT."** sits in two dark debossed label boxes (`--surface`, `--shadow-window`, radius 6px), letters in `--canvas` with `--text-raised`, boxes staggered right (start ≈ 30% from left; line 2 box shorter). Word group 2 **"PRESS IN."** sits bottom-left, two lines, debossed (`.h-pressed`). Paragraph + CTAs bottom-right (≈ 340px wide). A dark `hero__wash` vignette (`--deep`, absolute, z3) darkens the hero's lower edge.

```css
/* [M] moving light: an 80vmax paper-coloured disc, soft-light blended, centred at 34% / 30% */
.hero__light { position:absolute; left:34%; top:30%; width:80vmax; height:80vmax; margin:-40vmax 0 0 -40vmax;
  border-radius:50%; pointer-events:none; mix-blend-mode: soft-light;
  background: radial-gradient(closest-side, rgb(247 232 210/.85), rgb(247 232 210/.3) 55%, transparent);
  animation: hero-light 16s ease-in-out infinite alternate; }
@keyframes hero-light { from { transform: translate(-18vw,-12vh); } to { transform: translate(34vw,16vh); } }
```
- [M] Layout: `.hero__inner` grid `minmax(0,1fr) minmax(280px,29vw)`, column-gap 4vw, padding `calc(68px + 6vh) 6vw 7vh var(--gutter)`. Words: `font-size: min(16vh, 11.2vw)`; raised lines `margin-left: 23vw`, second raised line `margin-top: 1.4vh`, first pressed line `margin-top: 3.4vh`. Raised word padding `.07em .2em .02em .18em`, lh .92; pressed lh .96, no padding. Aside bottom-right, gap 26px, paragraph 18px/1.45.
- [M] Load-in: raised lines `hero-lift` (from `translate(-4px,16px) scale(.965)`), pressed lines `hero-sink` (from `translate(5px,-10px) scale(1.02)`), aside `hero-shift` (from `translateY(14px)`); 1s (aside .9s) `cubic-bezier(.2,.75,.15,1)`, delays 0 / .08 / .14 / .22 / .28s, `animation-fill-mode: backwards`.
- [M] `hero-sway-raised` / `hero-sway-cut`: 16s ease-in-out infinite alternate on every `.hero__word`, interpolating `text-shadow` from `--text-raised` → `--text-raised-b` (x offsets mirror) and `--text-pressed` → `--text-pressed-b`. Plain keyframes on `text-shadow` interpolate fine, so no `@property` is needed.
- [M] Scroll: the hero is a paper **flap** over a `--surface` base. On scroll the flap stays pinned and scales to ≈.94 while `.hero__wash` (`--deep`) fades in (≈.16 opacity at 360px): the board sinks back as the next sheet slides over it. Light and sway pause while sinking.

### 7.2 Nav bar [M]
Header fixed, 68px. [M] The bar is **always** paper (`--canvas` + grain + `--shadow-sheet`), never transparent. `.nav__bar` hides on scroll-down with `translateY(calc(-100% - 32px))` and returns on scroll-up, **500ms `cubic-bezier(.2,.7,.2,1)`**. Bar: flex, gap 30px, padding `0 3vw 0 var(--gutter)`; links gap 26px; wordmark Gabarito 22px caps with `--text-etched`. Links: 15px/600, dashed underline (see §6 links). `PT` language item. At ≤900px nav height 62px, column-gap 14px; at ≤767px links collapse behind `.nav__toggle`.

### 7.3 Scroll reveals [M]
31 reveals measured per pass: **slideUp ×18, scale-in ×11, fade ×3**, each fired once (no replay).
```css
.reveal { opacity: 0; }
.reveal[data-r="up"]    { transform: translateY(28px); }
.reveal[data-r="scale"] { transform: scale(.94); }
.reveal.is-in { opacity: 1; transform: none; transition: opacity var(--dur-mid) var(--ease-enter), transform var(--dur-mid) var(--ease-enter); }
@media (prefers-reduced-motion: reduce) { .reveal, .reveal.is-in { opacity:1; transform:none; transition:none; } }
```
Observer: `threshold: .15`, `rootMargin: "0px 0px -10% 0px"`, unobserve after first hit. Stagger children 60–90ms. Use slideUp for text blocks & rows, scale-in for swatches/cards/images, fade for decor.

### 7.4 Scroll-linked bands [I — verify]
- **Statement band** [M, corrected]: it is *not* raised-on-dark. The section bg is `--surface`, height 250svh, with a sticky 100svh stage holding ONE paper **flap** (`--canvas` + grain, top corners `--r-panel`, `--shadow-flap`) that rises from scale .94 to 1 over the sinking hero. On it, three huge **pressed** lines (Gabarito ≈123px, `--ink-2`, lines 1–2 indented 15vw) start faint (masked to ≈40–50% alpha). A **roller** presses them in one by one: a 3px line, dark top half / paper bottom half, faded ends, travelling down the stage, scrubbed to scroll. Pressed lines take `--text-raised-canvas`. A short note sits bottom-right (grid `1fr minmax(260px,27vw)`).
- **Finishes swatches** [M]: they enter as a **dealt stack of cards** (scale ≈.81, rotated ±5–9°, piled near the centre, z-index descending) and fan out to their grid cells, scrubbed to scroll.
- **Process band** [M, corrected]: a **horizontal track** inside a large die-cut window (`--surface`, `--shadow-window`, radius 6). Section height = `100svh + track distance`, sticky stage. The track holds intro text on dark (`--gray-light`), then 4 raised step cards (33vw wide, padding 26/26/22: caption "STEP 1", h3, copy, small visual), then an end CTA, translated on X and scrubbed to scroll.
- **Work rows:** the `work__rim` decor (z3) frames the window; photo likely drifts behind the sleeve (parallax ±20px).

### 7.5 Reduced motion
Honour `prefers-reduced-motion`: disable Lenis, hero light/sway, scrubs; keep end states visible.

---

## 8. Micro-interactions [M unless tagged]

| Element | Base | Hover | Active | Focus-visible |
|---|---|---|---|---|
| `.m-btn` (min-height 52, padding 0 26, radius 6, 16/600, lh 1, ls .01em) [M] | `--shadow-raised` | `--shadow-press` + `translate(1px,2px)` **and** `::after { opacity: 1 }`, where `::after` is a `--shadow-well` overlay (opacity transition .22s) [M] | same as hover | `outline: 3px solid var(--accent); outline-offset: 2px` |
| `.m-icon-btn` (46px circle; FAQ mark 38px) [M] | raised | `--shadow-press` + well overlay; glyph `scaleX(.8)` | — | 3px outline |
| `.m-link-2` nav/text link (15/600, lh 1.2, ls .01em, padding 4px 0 5px) [M] | `linear-gradient(90deg, currentColor 55%, transparent 0)` at `background-size: 7px 1px`, repeat-x, bottom | `background-size: 3px 2px` (dashes get denser and thicker), 250ms [M] | — | 3px outline |
| `.m-field__input` (54px, textarea 150px, radius 6, padding 14 16, 17px) | transparent + `--shadow-well`, no border [M] | none | — | 2px outline `--accent`, offset 2 |
| FAQ `details > summary` (padding 28px 0; question in Gabarito caps with `--text-raised-canvas`) [M] | rows separated by 3px `--shadow-well` creases; raised 38px circle with a plus | — | open: circle switches to `--shadow-well`, vertical bar rotates 90°→0 (.3s `--ease-ui`) | 3px outline, offset 4 |
| Cards/swatches | raised | **none measured** — the site is deliberately still. Optional: 2px lift via `--shadow-raised` only if brief demands. | | 3px outline |

Transition recipes:
- Buttons: `box-shadow .22s cubic-bezier(.3,.7,.2,1), transform .22s cubic-bezier(.3,.7,.2,1)`
- Links: `background-size .25s ease`
- Shadows generic: `box-shadow .25s ease`
- Cursor: `pointer` on buttons/links/summary; the site also sets pointer on many non-interactive nodes — don't copy that.
Tap targets: pad small links to ≥44px hit area (originals are 20–28px high).

**Audit AI additions (review 2026-10-22, not in the reference)**. All follow "interaction = moving toward pressed", and none apply under reduced motion:
- Button `:active` → `--shadow-press-deep` + `translate(2px,3px)`, 90ms (hover stays `--shadow-press`).
- Hero label boxes (`.hero__channel`) on hover → `--shadow-window-press`, letters `translate(1px,2px)`, 500ms `--ease-ui`.
- Hero pressed words on hover → `filter: url(#cut-relief-deep)` + `translate(1px,1px)`.
- Wordmark: rests raised (`--text-raised-canvas`), hover → pressed (`--ink-2`, `--text-pressed`, `translate(1px,1px)`), 220ms.
- Nav links: hover nudges `translateY(1px)`; any `.link:active` → `translateY(1px)`.
- `TextLink arrow`: a trailing → slides 4px right on hover; the dashed underline stays on the label.
- Hero light follows the pointer (fine pointers only): `--px/--py` eased 6% per frame, applied to `.hero__light-frame` as up to ±4vw/±4vh. The 16s drift keeps running inside it.
- Hero light softened per review: a warm tone (55% `--paper-hi` mixed into `--canvas`) at 42% → 14% → 0, instead of near-white 85% → 30%. It should read as a sheen, never a glare.

Dashed underline implementation:
```css
/* [M] */
.link { background: linear-gradient(90deg, currentColor 55%, transparent 0) 0 100% / 7px 1px repeat-x;
        padding: 4px 0 5px; transition: background-size .25s ease; }
.link:hover { background-size: 3px 2px; }
```

---

## 9. Voice & copy (so generated text feels the same)
Sentence case in source, uppercase on screen. Headlines ≈ 3 words, declarative, never questions. First-person plural ("we"). Plain reading level (~13 words/sentence). CTA verbs: **send / see / contact / start / order**. Recurring phrase pattern: concrete material nouns + verbs of making. Pull-quote = one reflective sentence + attribution in caption style. FAQ questions are real, short, practical.

---

## 10. Page blueprint (slots) — heights/bg from scan [M], layout from screenshots

Viewport reference: 1182×937. Section padding 141px unless noted. `H` = header (68px fixed, overlaps hero).

| # | Slot | Height | BG | Container / grid | Content & visuals |
|---|---|---|---|---|---|
| H | Header | 68 | transparent→canvas | 1055px inner | Wordmark (Gabarito 700 ~20px uppercase) · 5 links · lang · `Order a kit` raised button (132×52) |
| 1 | **Hero** | 938 (100vh) | canvas + grain + light + wash | 1019px, grid `2fr 1fr` | §7.1; paragraph (18/1.55) + primary raised CTA + dashed secondary link |
| 2 | **Craft statement** | 2343 | `--surface` dark, grain | 1019px, `2fr 1fr` | Three huge raised words, scroll flaps (§7.4) |
| 3 | **Six finishes** | 1574 | canvas | 1013px; head `1fr 1fr` align end; body 3×2 grid gap 47 | H2 (4 lines, pressed) left + 17px intro right. 6 square raised swatch cards (308px) each with one finish visual (§6.3–6.8), then h3 (22px uppercase) + 17/26 copy. |
| 4 | **Process, 4 moves** | 2560 | canvas | 1013px, 2 cols | Head + 4 raised step cards (390×477, padding 26/26/22, step number, title, copy, small visual) + CTA "Start with a sample kit"-style link |
| 5 | **Work / proof** | 2351 | canvas | 1013px; head `1fr 1fr` | 4 alternating rows (3 columns each: sleeve card · photo · text+spec table). Sleeve = tall raised card with dark die-cut window (rect or circle; circle windows reveal a crop of the photo), name label bottom-left in Gabarito caps. Rows mirror each other. Spec table: FINISH / BOARD / RUN dotted rows. |
| 6 | **About / studio** | 1475 | canvas page + inset dark panel (`--surface`, radius `--r-panel`, 18px margin) | 975px, 12-col, row gap 84 / col gap 28 | Raised headline (3 lines) + intro; wide photo + two paragraphs; pull-quote (Gabarito 31–33px caps, canvas) + attribution caption + portrait photo (radius 6) |
| 7 | **Specs / materials** | 1990 | canvas | 453px text column + wide list | H2 + paragraph left, photo right; 5 rows separated by 1px rules: cross-section diagram · name (caps) + spec caption · `BEST FOR` · `TAKES`. Ends with punch-disc visual (296px) + small caps heading + 17px copy. |
| 8 | **Pricing / kit** | 1128 | canvas | 437px column | H2 + 3 tier rows (name, price big, one-line note) + CTA |
| 9 | **FAQ** | 754 | canvas | 564px | H2 "Before you ask"-style + 5 `details` rows (summary padding 28px 0, 17px, plus/chevron glyph) |
| 10 | **Contact** | 1081 | canvas | 1013px; title flex column | Giant H2; form: name (text), email (email), message (textarea 150px), submit button; fields = pressed wells |
| F | **Footer** | 662 | canvas | 4 equal cols (208px each) | Wordmark, link columns, small print (content not captured — design your own) |

Imagery rules: webp, lazy, always alt, `object-fit: cover`, radius 6px, aspect ratios 1.5:1 (557×371), 0.8:1 (364×455), 1.25:1 (364×291). Photos are warm/orange-biased macro shots of material; keep a warm grade so they sit in the palette. No icons set; the few glyphs are simple type-like marks.

---

## 11. Responsive [M]
Desktop-first. Breakpoints **900px** and **767px** only (don't add more).
- ≤900px: header 62px, nav column-gap 14px.
- ≤767px: all 2/3/12-col grids → 1 column (15 grids), spacing shrinks ~90% from desktop *ratios*, body 17px, nav collapses behind a toggle, hero words fluid via `clamp`.
- Type is fluid via `clamp()`/vw; use `vw`+`vh` clamps for gutter/section-pad as in `tokens.css`.
- Hero light animation off on mobile if jank.

## 12. Accessibility
Focus rings on every interactive element (`:focus-visible`), skip link (missing in original — add), `prefers-reduced-motion`, 44px tap targets, one H1, landmarks (header/main/footer/nav), alt text everywhere, `details/summary` for FAQ, form labels (original has them: "Your name", "Email", "What should we pack?").

## 13. KNOWN GAPS & CONFLICTS in the source data (read before building)
1. **Shadows are truncated** in every scan file → repaired in §5/`tokens.css` [R]. Verify by inspecting `.m-btn`, `.finishes__swatch`, `.work__sleeve`, `.hero__channel`, `.m-field__input` computed `box-shadow` on the live site.
2. `ai-prompt.txt` **headline-to-section mapping is shifted** (and the Rebuild Checklist offsets it by one more). Trust §10 here (matched to screenshots).
3. Generic template lines contradict the real site: "pills 9999px", "primary button radius 0 / transparent / 28px padding" (that is the FAQ summary row, not a button), "hover: no change" (real `.m-btn` hover = press), "card padding 5px", "no shadows" signature device, "ghost" labels.
4. Screenshots of bands 2 and 4 are blank (content hidden until scroll). Their internals are [I].
5. Text colour contrast numbers on the dark band are mis-computed (1.5:1 / 1:1) — real: canvas text on `#47331f` ≈ 6:1.
6. Not captured: footer content, mobile layout images, hero sway exact keyframes, process-card inner content, hover on swatches/cards, icon glyph shapes.
7. Hover on `.m-link-2` is declared as a `background-size` transition but start/end sizes weren't recorded.

## 14. Acceptance checklist
- [ ] Tokens only (no stray hex/px); fonts self-hosted; CLS ≈ 0.
- [ ] Grain visible on canvas and dark band; light source always top-left.
- [ ] Hero matches `reference/screenshots/01-hero.jpg` at 1182×937 (word placement, relief, wash, paragraph/CTA position).
- [ ] Six-finish swatches match `03-finishes.jpg` (relief direction, sizes, spacing 47px).
- [ ] Work rows alternate, windows reveal photos (`05-work.jpg`); studio panel matches `06-studio.jpg`; spec list + punch disc match `07-materials.jpg`.
- [ ] Hero light loops 16s; nav bar slides 500ms; reveals fire once; Lenis + ScrollTrigger synced.
- [ ] Button hover = press (translate 1px,2px + shadow swap, 220ms); links underline 250ms; focus rings visible.
- [ ] 900/767 breakpoints behave; reduced-motion verified; Lighthouse a11y ≥ 95.

---

# PART B — Audit AI product UI

## 15. Landing page copy deck (original copy, same voice as §9)
Map to §10 slots. Headlines are written sentence-case, rendered uppercase. Anything marked *sample* must be labelled as sample data on screen.

| Slot | Headline | Content |
|---|---|---|
| Header | Wordmark **AUDIT AI.** | Links: Checks · Process · Findings · Sources · Contact · `Start a review` (button). Add a quiet "AI & services" link (disclosure). |
| 1 Hero | Raised in two label boxes: **"Check first."** · Pressed bottom-left: **"Publish sure."** | Para: "Audit AI reviews every draft against your approved guidelines, facts and assets before it goes live. Each finding shows its source, and a person makes the final call." CTAs: `Start a review` + dashed link `See a sample finding` |
| 2 Statement (dark) | **"Claims need proof. / Sources stay current. / People decide."** | Three huge raised lines, scroll-flap animation (§7.4) |
| 3 Six checks | **"Six checks before anything ships"** | Intro: "Every draft passes six checks. Each finding names the rule or source behind it." Six swatch cards (§0.1 mapping): *Tone* — "Does it sound like you?" · *Terminology* — "Your words, spelled your way." · *Facts* — "Numbers match the approved sheet." · *Claims* — "Big promises need evidence." · *Visuals* — "Colours and logos stay on palette." · *Accessibility* — "Readable by everyone, first time." |
| 4 Process | **"Draft to approved in four moves"** | 1 *Import what's approved* (guidelines, fact sheet, claims, assets) · 2 *Submit the draft* (text, doc, image) · 3 *Review with evidence* (explain, suggest, re-check) · 4 *Approve and record* (roles, audit trail). CTA `Try it on one draft` |
| 5 Proof | **"Findings we have caught"** (*sample data*) | 4 rows using the sleeve+window+photo layout; replace photo with a **screenshot crop of the real review UI**. Spec table CHECK / SOURCE / RESULT: ① "Lasts 24 hours" · Fact sheet v3 · *Contradicted (approved: 12 hours)* ② "India's number-one eco-friendly solution" · Green-claims pack · *Unsupported — qualifier needed* ③ "BUY NOW!!!" · Accessibility + tone rules · *Two findings* ④ Brand Guide v4 uploaded · Source Watch · *3 approved items re-flagged* |
| 6 Oversight (dark panel) | **"People stay in charge"** | Intro: "Audit AI proposes. Reviewers accept, edit, dismiss or escalate." Statement in the pull-quote style: **"Missing evidence means unverified, never false."** — attribution caption "Audit AI design principle" (not a fake person). Right visual: the Data Passport card inside a die-cut window. |
| 7 Sources | **"Five sources we read"** | Rows w/ cross-section-style glyph · name · USED FOR · READS: Brand guidelines — tone, terms — PDF, DOCX · Fact sheet — numbers, dates — CSV · Approved claims — safe wording, expiry — library · Regulation packs — claims law — India green claims first · Approved assets — palette, logos — PNG, SVG. Punch-disc footer: **"Confidential stays local."** "Sources marked confidential never go to an external model." |
| 8 Roles | **"Three roles, one workflow"** | Rows replace pricing tiers: *Creator* — submits, fixes · *Manager* — one-click sign-off on clean items · *Reviewer* — decides high-risk findings. |
| 9 FAQ | **"Before you ask"** | Does Audit AI rewrite my content? · Where does my data go? · What if there is no evidence? · How are confidential files handled? · Is this legal advice? |
| 10 Contact | **"Check something."** | Fields: Your name · Email · "What are you publishing?" · `Start a review` |
| Footer | Wordmark · Product · Trust (Data Passport, AI & services, Limitations) · Team CodeNinjas |

## 16. Status language (the only place new hues are allowed)
The palette rule "no new hues" (§1.4) is relaxed **only** for evidence/status inside the app, because green/amber/red evidence colouring is a required feature (heatmap). Rules: low saturation, never colour alone (always glyph + label + relief), text stays `--ink`.

| Status | Meaning | Relief | Text/glyph colour | Tint fill (on canvas) | Glyph |
|---|---|---|---|---|---|
| **Supported** | Matches an approved source | raised chip | `--ok #35441a` (5.2:1) | `rgb(91 107 42 / .30)` (ink on tint 5.4:1) | ✓ |
| **Unverified** | No evidence found | flat, dashed outline | `--warn #5e3408` (5.3:1) | `rgb(217 140 89 / .50)` (ink on tint 6.2:1) | ? |
| **Contradicted** | Conflicts with an approved source | pressed chip | `--bad #6f1f12` (5.5:1) | `rgb(138 47 31 / .30)` (ink on tint 4.8:1) | ≠ |
| **Source withdrawn** | Evidence changed/removed (Source Watch) | dark die-cut chip, canvas text | `--canvas` on `--surface` | — | ↻ |
| **Protected span** | Intent-lock must-keep text | pressed chip, `--ink-2` text | `--ink` | `rgb(31 20 11 / .10)` | padlock (inline SVG) |

On dark surfaces use `#a8b86a` / `#e0a15f` / `#e08a73` (≥4.5:1 on `--surface`). Severity (High / Med / Low) = ●●● / ●●○ / ●○○ + word, never colour. Contrast values verified against `#d4b08f`.

## 17. App shell & screens
Shell: same fixed 68px header (no hide-on-scroll in the app), `--shadow-sheet`; left nav is **not** used — use a top tab row (pressed-pill-free, dashed-underline active tab). Page container 1160px, dense grid, section padding 40–64px (app is denser than the marketing page; keep paper grain, relief and 6px radius). Lenis is **off** inside `/app`. Motion budget in app: 220ms press/hover, 500ms panel slide, no scroll-scrub.

| # | Route | Screen | Layout & key UI |
|---|---|---|---|
| A | `/app` | **Workspace** | Queue table (dotted rows): title · channel · status · risk tier · owner · updated. Filters as pressed toggles. Header stats row (3 raised cards): Awaiting review · High-risk · Evidence coverage avg. |
| B | `/app/new` | **New submission** | Paste text / upload PDF·DOCX·PNG·JPG; channel select (Website, Social, Email, Product page, Ad); sensitivity toggle (Confidential → "local model only" hint); extracted-text preview beside images (OCR) with edit-before-check. Fields = pressed wells. Submit = `Run checks`. |
| C | `/app/review/[id]` | **Review (core screen)** | 3 columns ≈ 5/4/3 on desktop. **Left:** document with **evidence-coverage heatmap** (sentence tinted ok/warn/bad per §16) + top coverage bar ("68% supported"). **Middle:** findings list (grouped by check, filter by severity/status) → selected **FindingCard**. **Right:** **EvidenceWindow** (die-cut dark well with the source excerpt, source name/version/page, "approved value vs found value"), then the **Data Passport** drawer button. Sticky bottom action bar: `Accept` (raised primary) · `Edit` · `Dismiss` · `Escalate`; all require explicit click, none automatic. Role-aware: Creators see Accept/Edit only. |
| D | (in C) | **Suggestion + Intent-lock** | Creator/reviewer selects must-keep spans (price, date, product name, CTA) → they become **protected chips**. Suggestion shown as **word-level diff** (removed = `--ink-2` strike, added = underline), protected spans locked. After generation show a **RecheckStamp**: embossed circular stamp "Re-checked 4/4" (or "3/4 — retry"). Fallback buttons: "Use approved claim wording" / "Remove claim". |
| E | `/app/library` | **Library** | Tabs: Guidelines · Fact sheet (key-value table, CSV import) · Approved claims (owner, evidence doc, channels, **expiry** badge) · Regulation packs (toggle per workspace, "guidance not legal advice" note) · Assets (palette swatches with hex, logos). Each source row: sensitivity label, version, `Withdraw` button. |
| F | `/app/source-watch` | **Source Watch** (named improvement #1) | Timeline of source versions; "Upload v4" shows a diff summary and a live list of approved items that flip to **Source withdrawn / re-flagged** with reason; button `Send back to review queue`. Start with manual `Withdraw source` (fallback), then automatic diff. |
| G | `/app/scorecard` | **Trust Scorecard** (named improvement #2) | Big gauges: **Catch rate** (target ≥85%) and **False positives** (target ≤15%), per-check breakdown table, version-over-version line chart, "50-item seeded test set · 15 held out" label, `Run evaluation` button, live false-positive rate from reviewer Dismiss decisions. Honest labelling: seeded vs real data. |
| H | `/app/insights` | **Insights / Guideline health** | Top violated rules, repeats by team & channel, trend; "Rule 2.4 dismissed 70% of the time — suggest rewrite" cards (alert at ≥50% dismissal over 10 decisions); contradictory-source pairs list. Seed 100 synthetic submissions and badge them **Seeded**. |
| I | `/app/audit/[id]` | **Audit trail & pack** | Vertical timeline (who, what, when, finding, evidence, decision), revision history with diff, comments thread, `Export audit pack (PDF)`. |
| J | (drawer) | **Data Passport** | Per-submission list: which model/service processed which text, redaction applied, confidential sources = "local only / no external call". Empty call log state is a *feature* — show it clearly. |
| K | (global) | **Approval workflow** | Stepper chip row: Draft → Checked → In review → Approved / Escalated; risk-tier routing (High → Reviewer, Clean → Manager one-click). |

Empty / loading / error states are designed: empty = die-cut window with one line of guidance; loading = grain shimmer limited to opacity (respect reduced motion); LLM-down = banner "Rules-only mode — AI checks unavailable" (rules + accessibility checks keep working).

## 18. New components (build with primitives from §6 and §8)
`StatusChip` (4 states + protected) · `SeverityMarks` · `FindingCard` (check icon, title, severity, status, "why flagged", source link, suggestion, 4 actions) · `EvidenceWindow` (dark die-cut, canvas text, mark the matching excerpt with `--text-raised`) · `CoverageBar` (pressed trough, raised fill segmented ok/warn/bad) · `HeatText` (sentence-level highlight spans, keyboard focusable) · `DiffView` (word diff + protected chips) · `RecheckStamp` · `DataPassport` · `RoleStepper` · `AuditTimeline` · `ScoreGauge` · `TrendChart` (lines in `--ink`, `--ink-2`, `--accent`; direct labels; grid in rgb(31 20 11/.15); no rainbow) · `SourceRow` (version, sensitivity, expiry, Withdraw) · `Tabs` (dashed underline) · `Toast` (raised, 500ms) · `ConfirmDialog` (die-cut backdrop, focus-trapped, Radix Dialog).
Check-category icons are the six finish visuals at 40px (CSS-drawn, §0.1).

## 19. Data contracts (frontend works against typed mocks first)
```ts
type CheckKind = 'tone'|'terminology'|'facts'|'claims'|'visual'|'accessibility';
type EvidenceStatus = 'supported'|'unverified'|'contradicted'|'source_withdrawn';
type Severity = 'high'|'medium'|'low';
type Role = 'creator'|'manager'|'reviewer'|'admin';
type Channel = 'website'|'social'|'email'|'product'|'ad';

interface Source { id:string; name:string; type:'guideline'|'fact_sheet'|'claim'|'regulation_pack'|'asset';
  version:number; sensitivity:'public'|'internal'|'confidential'; expiresAt?:string; withdrawnAt?:string }
interface Evidence { sourceId:string; sourceVersion:number; excerpt:string; location?:string; // page/section
  approvedValue?:string; foundValue?:string; similarity?:number }
interface Finding { id:string; submissionId:string; check:CheckKind; severity:Severity; status:EvidenceStatus;
  span:{start:number;end:number}; title:string; whyFlagged:string; evidence:Evidence[];
  suggestion?: Suggestion; origin:'rule'|'retrieval'|'llm'; }   // origin powers explainability + Data Passport
interface Suggestion { id:string; text:string; diff:{op:'keep'|'add'|'del'; text:string}[];
  protectedSpans:{start:number;end:number}[]; recheck:{passed:number; total:number; failures?:string[]};
  fallback?:'approved_claim'|'remove_claim' }
interface Decision { id:string; findingId:string; by:string; role:Role; action:'accept'|'edit'|'dismiss'|'escalate';
  note?:string; at:string }
interface Submission { id:string; title:string; channel:Channel; format:'text'|'pdf'|'docx'|'image';
  sensitivity:'normal'|'confidential'; status:'draft'|'checked'|'in_review'|'approved'|'escalated';
  risk:'high'|'clean'|'normal'; coveragePct:number; ownerId:string; updatedAt:string }
interface PassportEntry { service:string; model?:string; local:boolean; redacted:boolean; textRangeLabel:string; at:string }
interface ScoreRun { id:string; version:string; catchRate:number; falsePositiveRate:number;
  perCheck:Record<CheckKind,{catch:number;fp:number}>; heldOutN:number; at:string }
```
Put mocks in `/mocks` + MSW handlers; swap to the real API by changing one base URL. Seed the demo scenarios from §15 row 5 so the video/demo never depends on the backend being up.

## 20. Frontend stack (aligned with the team deck: Next.js + TypeScript)
Next.js (App Router) · React 19 · TypeScript (strict) · Tailwind CSS v4 (`@theme` from `tokens.css`) · Radix UI primitives (Dialog, Tabs, Popover, Tooltip, Toggle, Checkbox) re-styled to the pressed-paper kit · TanStack Query (server state) + Zustand (review-screen UI state: selection, protected spans) · React Hook Form + Zod · `diff` (jsdiff) for word diffs · Recharts or visx for charts (custom-styled per §18) · GSAP + ScrollTrigger + Lenis **marketing page only** · Fontsource Gabarito + Instrument Sans · MSW for mocks · Playwright (visual QA + e2e demo path) · Vitest only for diff/protected-span logic.
Rendering: marketing route static; `/app/*` client-heavy with server auth. Accessibility: all state conveyed by glyph+label (not colour), keyboard path through finding → decision, `aria-live` for re-check results.

## 21. Build priorities (mapped to the judging rubric)
Round 2 weights: core workflow end-to-end **30** · technical depth/reliability **25** · progress vs plan **20** · **three named improvements 15** · usability **10**. Round 3 adds completeness, reliability, real-world fit, documentation.
1. **Submit → Review (C) → Decide → Audit (I)** with mocks — a full demo path first.
2. Evidence: EvidenceWindow + heatmap + CoverageBar.
3. **Intent-lock** diff + RecheckStamp (D).
4. **Trust Scorecard** (G).
5. **Source Watch** manual withdraw → re-flag view (F).
6. Accessibility findings display; Library (E); Data Passport (J).
7. Insights (H), role routing (K), audit-pack export.
8. **Landing page last** — hero + three sections is enough until the app works; judges test the product, not the brochure.

## 22. Frontend acceptance (Audit AI)
- [ ] A judge can run: upload → checks → open a finding → see evidence → accept/edit/dismiss/escalate → see it in the audit trail, with no dead ends.
- [ ] Every finding shows *why*, *which source/version*, *evidence excerpt*; unverified is never labelled false.
- [ ] Intent-lock: protected spans cannot change in a suggestion; re-check badge visible.
- [ ] Scorecard shows catch rate / false-positive rate vs 85% / 15% targets, with seeded-data labelling.
- [ ] Source Watch re-flags dependants and sends them to the queue.
- [ ] Data Passport + "AI & services" disclosure reachable from every review screen; confidential sources show "local only".
- [ ] Rules-only fallback banner works when the LLM mock is switched off.
- [ ] Part A acceptance (§14) still passes for the marketing page; app screens pass keyboard + contrast checks.
