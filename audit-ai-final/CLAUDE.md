# Audit AI — project memory for Claude Code

Audit AI is a brand-governance platform that reviews content BEFORE publication against approved guidelines, facts and assets (Inkloom AI hackathon, team CodeNinjas). I own the frontend in `./frontend`. Do not touch other folders.

## UI authority (read before any UI work)
- `design/DESIGN.md` — visual system (Part A, §1–14) and product UI (Part B, §15–22). Tags: [M] measured, [R] reconstructed (calibrate), [I] inferred (verify).
- `design/tokens.css` — the only source for colours, fonts, radii, shadows, durations.

## Style in one paragraph
"Pressed paper": warm cardboard canvas (#d4b08f) with grain, light from the TOP-LEFT, raised = approved/available, pressed = contradicted/input, dark die-cut window = evidence, dashed = unverified. Gabarito 700 uppercase headings, Instrument Sans body, radius 6px (no pills), motion 220ms buttons / 250ms links / 500ms reveals / 16s hero light, no bounce.

## Rules
- Tokens only. No new hues except evidence-status colours (DESIGN.md §16, app only).
- Never convey status by colour alone. "Unverified" is never "false". Humans decide; never auto-apply suggestions.
- Every animation needs a `prefers-reduced-motion` fallback. Keyboard-accessible, visible focus rings.
- Original copy only (DESIGN.md §15). Never copy relevovinco.com text, images or brand.
- Use exact feature names: Source Watch, Trust Scorecard, Intent-lock, Data Passport, Evidence coverage.
- After any visual change: screenshot with Playwright (1182×937 and 390×844) and compare to the reference screenshots.
- Ask before adding dependencies or changing section order.
- Disclose in README: AI-assisted code (Claude Code) and the style reference (relevovinco.com public style, re-implemented, nothing copied).
- Hackathon: write product code only inside the official build window; commit often with clear messages.

## Stack
Next.js (App Router) + React 19 + TypeScript strict + Tailwind v4 + GSAP/ScrollTrigger + Lenis (marketing page only) + Fontsource (Gabarito 700, Instrument Sans 400/600). App-phase extras are listed in DESIGN.md §20.
