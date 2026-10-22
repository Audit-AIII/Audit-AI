# START PROMPT — Landing page + hero (Audit AI)

How to use: in VS Code open your repo folder, open the terminal, run `claude`, then paste ONE line:

> Read prompts/01-landing-and-hero.md and execute it.

(Or paste the block below directly.)

---

```
TASK
Build the Audit AI marketing landing page (hero + all sections) in ./frontend, replicating the "pressed paper" look, motion and micro-interactions of relevovinco.com, but with MY content. Scope is the landing page ONLY — no app screens yet.

PRODUCT (for copy and context)
Audit AI is a brand-governance platform that reviews content before publication against approved guidelines, facts and assets. It checks tone, terminology, facts/messaging, claims, visuals and accessibility; every finding explains why and cites its source; suggestions preserve the creator's purpose; humans make the final call. Primary CTA: "Start a review". Secondary: "See a sample finding".

READ FIRST (fully, in order)
1. CLAUDE.md (auto-loaded)
2. design/DESIGN.md — Part A §1–§14 and §15 (landing copy deck). Skip §16–§22 for now.
3. design/tokens.css
4. LOOK at every image in design/reference/screenshots/ using the Read tool. They are the visual target.

STACK
Next.js (App Router) + React 19 + TypeScript strict + Tailwind v4 (@theme from tokens.css) + GSAP + ScrollTrigger + Lenis + @fontsource-variable/gabarito + @fontsource-variable/instrument-sans. Nothing else without asking.

STEPS
1. Plan (short, then continue without waiting): 10 bullets on the design system in your own words, the folder structure, and the component list. Create the Next.js app in ./frontend.
2. Calibrate [R]/[I] values: use Playwright (install chromium if needed) against https://relevovinco.com at 1182×937 to read computed box-shadow, text-shadow, transform, transition, animation and background-image for .m-btn (+hover), .m-link-2, .m-field__input, .nav__bar, .hero__word, .hero__channel, .hero__wash, .finishes__swatch, .work__sleeve, .work__rim, .process__step, .materials__disc, .faq__summary; save to design/probe.json and correct design/tokens.css and DESIGN.md §5–§8. If the site is unreachable, skip this and calibrate visually against the screenshots instead, and tell me.
3. Foundations: tokens in @theme, self-hosted fonts, .paper grain, container/section primitives, Lenis + ScrollTrigger sync, reveal system (IntersectionObserver, once), reduced-motion guard.
4. Primitives: Button, Link (dashed underline), Field/Textarea (pressed wells), Card, Swatch, SpecTable, Disclosure (details/summary), Heading (pressed / raised), Header (fixed 68px, hide/show on scroll 500ms, mobile toggle).
5. HERO FIRST. Pixel-match design/reference/screenshots/01-hero.jpg at 1182×937:
   - header "AUDIT AI." + links Checks · Process · Findings · Sources · Contact + "Start a review" button
   - "CHECK FIRST." raised letters inside two staggered dark debossed label boxes
   - "PUBLISH SURE." debossed, bottom-left, two lines
   - paragraph + "Start a review" button + dashed link "See a sample finding" bottom-right
   - hero wash vignette, 16s moving light (soft-light), word sway
   STOP after the hero: show me Playwright screenshots next to the reference and list remaining differences. Wait for my OK.
6. Remaining sections in DESIGN.md §15 order (statement band, six checks, four-move process, findings we have caught [label as sample data], people stay in charge, five sources + punch disc, three roles, FAQ, contact form, footer with an "AI & services" link). Each section: build → screenshot → compare with its reference screenshot → fix (max 3 rounds).
7. Responsive (breakpoints 900px and 767px only), accessibility pass (skip link, focus rings, one H1, 44px tap targets), performance (webp, lazy, no CLS).
8. README: run instructions, token map, motion map, known deviations, disclosure of AI-assisted code and the style reference.

HARD RULES
- Tokens only (colours, fonts, radii, shadows, durations). No pills (radius 6px). No bounce. Light source top-left. Headings written in sentence case, rendered uppercase.
- Every animation has a prefers-reduced-motion fallback.
- Original copy from DESIGN.md §15 only. Do not copy relevovinco.com text, images or brand. Use neutral warm placeholders for photos and mark them TODO; for "Findings we have caught" use CSS-drawn UI snippets labelled "Sample data".
- Commit after each step with a clear message.

DONE WHEN
Landing page runs with `npm run dev`, matches the reference screenshots closely at 1182×937 and works at 390×844, and DESIGN.md §14 acceptance checks for the marketing page pass.
```
