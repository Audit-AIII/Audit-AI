# Claude Code prompt — Audit AI frontend (paste as your first message)

Setup: put this folder in your repo as `./design/` (so `./design/DESIGN.md`, `./design/tokens.css`, `./design/reference/screenshots/`). Frontend lives in `./frontend`. Start Claude Code in the repo root.
Hackathon rule reminder: write product code **inside the official build window**, commit often with clear messages, and disclose Claude Code + the style reference (see DESIGN.md §0.2).

---

```
You are the frontend engineer for "Audit AI", a brand-governance platform that reviews content BEFORE publication against approved guidelines, facts and assets (Inkloom AI hackathon, team CodeNinjas). I own ./frontend. Do not touch other folders.

PRODUCT
Creators/agencies/AI tools submit content; Audit AI checks tone, terminology, facts/messaging, claims, visuals and accessibility; every finding explains WHY, cites the approved source excerpt (evidence), and suggests a fix that preserves the creator's purpose. Humans decide (Accept / Edit / Dismiss / Escalate). Principle: missing evidence = "unverified", never "false".
Three improvements the judges will look for, use these exact names in the UI: Source Watch (re-flag approved content when its source changes), Trust Scorecard (live catch-rate / false-positive measurement vs 85% / 15% targets), Intent-lock (protected spans + re-checked suggestions).

READ FIRST (in this order, fully)
1. ./design/DESIGN.md — Part A visual system (§1–§14) and Part B product UI (§15–§22). It is the authority. Tags: [M] measured, [R] reconstructed (calibrate), [I] inferred (verify).
2. ./design/tokens.css
3. Look at EVERY image in ./design/reference/screenshots/ (Read tool). They show the "pressed paper" style to reproduce: warm cardboard canvas, grain, top-left light, raised vs pressed relief, Gabarito 700 uppercase headings + Instrument Sans body.

STACK
Next.js (App Router) + React 19 + TypeScript strict + Tailwind v4 (@theme from tokens.css) + Radix primitives + TanStack Query + Zustand + React Hook Form + Zod + jsdiff + Recharts (custom-styled) + MSW mocks + Playwright. GSAP + ScrollTrigger + Lenis ONLY on the marketing page. Self-host Gabarito 700 and Instrument Sans 400/600 via Fontsource. Ask before adding anything else.

WORKFLOW — stop at each checkpoint and wait for my OK
Phase 0 — Plan only (no app code)
  a. ≤15 bullets: the design system in your own words (light direction, raised/pressed/die-cut/dashed semantics, palette, type, motion, the status colours exception).
  b. Proposed folder structure, route map (DESIGN.md §17), component list (§18) and the order you'll build in (§21).
  c. Use Playwright against https://relevovinco.com (1182×937) to dump computed box-shadow, text-shadow, transform, transition, animation and background-image for: .m-btn (+hover), .m-icon-btn, .m-link-2, .m-field__input, .nav__bar, .hero__word, .hero__channel, .hero__wash, .finishes__swatch, .work__sleeve, .work__rim, .process__step, .materials__disc, .faq__summary. Save to ./design/probe.json and replace every [R]/[I] value in DESIGN.md §5–§8 and tokens.css with measured ones. Show me the diff.
Phase 1 — Foundations: scaffold, tokens in @theme, fonts, .paper grain, container/section primitives, reveal system (IntersectionObserver, once), reduced-motion guard, MSW + the TypeScript contracts from DESIGN.md §19 and seeded mock data for the four demo scenarios in §15 row 5 (24h vs 12h battery fact, "eco-friendly" green claim, "BUY NOW!!!", Brand Guide v4 drift).
Phase 2 — Primitives + /styleguide: Button, IconButton, Link, Field/Textarea (pressed wells), Card, Tabs, Dialog, Toast, StatusChip, SeverityMarks, Heading (pressed/raised), Header. Show every state (base/hover/active/focus) on /styleguide.
Phase 3 — CORE WORKFLOW FIRST (rubric priority): Workspace (A) → New submission (B) → Review screen (C: HeatText, CoverageBar, FindingCard, EvidenceWindow, action bar, role-aware) → Audit trail (I). Must work end-to-end on mocks before anything else.
Phase 4 — Named improvements: Intent-lock DiffView + RecheckStamp (D) → Trust Scorecard (G) → Source Watch (F, manual withdraw first). Then Library (E), Data Passport (J), Insights (H), roles/routing (K).
Phase 5 — Marketing page last: hero (pixel-match reference 01-hero.jpg at 1182×937, including the 16s moving light) + sections from DESIGN.md §15, then the rest if time allows.
Phase 6 — Responsive (900px and 767px), accessibility pass, README.

VISUAL QA LOOP (mandatory after each screen/section)
Run the dev server, screenshot with Playwright at 1182×937 and 390×844, compare with the reference style (screenshots for the marketing page; the styleguide for app screens), list concrete differences (shadow direction/strength, spacing, type, grain), fix, re-shoot. Max 3 rounds, then report what is still off.

HARD RULES
- Tokens only (colours, fonts, radii, shadows, durations). No new hues except the evidence-status colours in DESIGN.md §16. No pills (radius 6px). No bounce/spring. Light source always top-left.
- Never convey status by colour alone: glyph + label + relief. Severity = ●●● marks + word.
- Never auto-apply a suggestion or make a decision for a human. Unverified is never labelled false. Label seeded/sample data as "Seeded"/"Sample".
- Every animation has a prefers-reduced-motion fallback; full keyboard path through finding → decision; aria-live for re-check results.
- Show AI/external-service use: Data Passport and an "AI & services" disclosure reachable from every review screen; confidential sources show "local only".
- Rules-only fallback: when the mock LLM is off, show the "Rules-only mode" banner and keep rules + accessibility findings working.
- Original copy only (DESIGN.md §15); do not copy relevovinco.com text, images or brand.
- Ask me before: adding dependencies, changing routes/section order, or inventing product claims/metrics.

DELIVERABLE
Working app on mocks with a scripted demo path, /styleguide, README (run instructions, token map, motion map, component map, mock→real API swap, known deviations, disclosure of AI-assisted code and the style reference).
```

---

## Optional
- Copy `./design/DESIGN.md` to `.claude/skills/audit-ai-ui/SKILL.md` (add `name` and `description` frontmatter) so every session loads it.
- Add `CLAUDE.md.snippet` to your repo `CLAUDE.md`.
