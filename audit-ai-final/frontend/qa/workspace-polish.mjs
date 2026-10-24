// Workspace polish: one-row nav (stage track + Workspace menu), atmosphere, box shadows, tally,
// "AI is working" state. Real sign-in; one review is served (mixed verdicts, like safer-wording.mjs)
// because without an AI key every real claim result is the placeholder.
// AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/workspace-polish.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const WEB = "http://localhost:3000", API = "http://localhost:8000";
const T = "The Verde lasts 48 hours. It is the best bottle in India. It holds 750 ml. It is made in Pune.";
const cp = (s) => Array.from(s).length;
const span = (n) => ({ start: cp(T.slice(0, T.indexOf(n))), end: cp(T.slice(0, T.indexOf(n))) + cp(n) });
const f = (id, text, status, extra = {}) => ({ finding_id: id, category: null, severity: "medium", original_text: text, span: span(text), check_type: "retrieval",
  explanation: `${status} test`, verification_status: status, suggested_correction: null, requires_human_review: status !== "supported", evidence: [],
  rule_id: null, rule_type: null, scope: null, suggestion_basis: null, source_ids: null, dismissal: null, comment_count: 0, ...extra });
const review = {
  id: "polish-test", content_version_id: "cv", content_item_id: null, brand_id: null, title: "Polish test", version_number: 1, text: T,
  status: "needs_human_review", report_status: null, engine: { provider: "fallback", model_id: "test", prompt_version: "v", contract_version: "0.2.0" },
  error_summary: null, served_from_cache: false, required_reviewer_role: null, rules_status: "complete", rule_checks: [], locked_phrases: [],
  started_at: null, completed_at: null, created_at: "2026-10-25T10:00:00Z", updated_at: "2026-10-25T10:00:00Z",
  findings: [f("a", "The Verde lasts 48 hours.", "contradicted"), f("b", "It is the best bottle in India.", "unverified"),
    f("c", "It holds 750 ml.", "supported"), f("d", "It is made in Pune.", "unverified", { dismissal: { by_user_id: "u", at: "2026-10-25T10:05:00Z", note: null } })],
};

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = []; p.on("pageerror", (e) => errors.push(e.message));
const noScroll = async (w) => assert.ok((await p.evaluate(() => document.documentElement.scrollWidth)) <= w, `no horizontal scroll at ${w}`);
await p.route(`${API}/api/findings/*/comments`, (r) => r.fulfill({ status: 200, contentType: "application/json", headers: { "Access-Control-Allow-Origin": WEB }, body: "[]" }));
await p.route(`${API}/api/reviews/polish-test`, (r) => r.fulfill({ status: 200, contentType: "application/json", headers: { "Access-Control-Allow-Origin": WEB }, body: JSON.stringify(review) }));
await p.goto(`${WEB}/login?next=%2Fapp%2Fdraft`, { waitUntil: "networkidle" });
await p.fill("#a-email", "ben@seed.inkloom.demo"); await p.fill("#a-password", process.env.AUDIT_PASSWORD); await p.click("button[type=submit]");
await p.waitForURL("**/app/draft");

// 1) nav: one row, track with a tile under the current stage, no second link row
await p.waitForSelector(".track__tile");
assert.equal(await p.locator(".app__more").count(), 0, "second row removed");
const bar = await p.locator(".app__bar").boundingBox(); assert.ok(bar.height < 90, `one row at 1440 (${bar.height}px)`);
await p.waitForTimeout(600);
const tile = await p.locator(".track__tile").boundingBox(); const cur = await p.locator(".track__stage[aria-current=page]").boundingBox();
assert.ok(Math.abs(tile.x - cur.x) < 2 && Math.abs(tile.width - cur.width) < 2, "tile sits under the current stage");
assert.match(await p.locator(".track__stage[aria-current=page]").innerText(), /02\s*DRAFT/i);
// keyboard: the Workspace menu opens, Escape closes it and returns focus
await p.locator(".wsmenu__btn").focus(); await p.keyboard.press("Enter");
await p.waitForSelector(".wsmenu__panel.is-open");
assert.equal(await p.locator(".wsmenu__item").count(), 5);
await p.keyboard.press("Tab"); assert.equal(await p.evaluate(() => document.activeElement?.className), "wsmenu__item");
await p.keyboard.press("Escape");
assert.equal(await p.locator(".wsmenu__panel.is-open").count(), 0);
assert.equal(await p.evaluate(() => document.activeElement?.className), "wsmenu__btn", "focus back on the button");
await p.click(".wsmenu__btn"); await p.click(".wsmenu__item:has-text('Queue')"); await p.waitForURL("**/app/queue");
assert.match(await p.locator(".wsmenu__btn").innerText(), /Queue/, "button shows the current page");
assert.equal(await p.locator(".track__tile").count(), 0, "no tile off the stages");
console.log("ok  nav: one row, sliding tile under the current stage, Workspace menu (keyboard, Escape returns focus, shows current page)");

// 2) atmosphere + boxes
assert.equal(await p.locator(".app__ambient[aria-hidden=true]").count(), 1);
assert.equal(await p.locator(".app__ambient").evaluate((el) => getComputedStyle(el).pointerEvents), "none");
const shadow = await p.locator(".app__main .card").first().evaluate((el) => getComputedStyle(el).boxShadow);
assert.ok(shadow.split("px,").length >= 5, "raised shadow plus the deeper drop");
console.log("ok  backdrop is decorative (aria-hidden, no pointer events); cards carry the deeper outer shadow");

// 3) tally on a review with mixed results
await p.goto(`${WEB}/app/review?id=polish-test`); await p.waitForSelector(".tally");
const tally = await p.locator(".tally").innerText();
for (const re of [/4\s*findings/i, /1 dismissed/i, /1\s*≠ Doesn’t match/i, /0\s*⇄ Documents disagree/i, /2\s*\? Not proven yet/i, /0\s*§ Brand rule/i, /1\s*✓ Matches/i]) assert.match(tally, re);
assert.equal(await p.locator(".tally__cell").count(), 5, "fixed five columns");
assert.equal(await p.locator(".tally__cell", { hasText: "Brand rule" }).isDisabled(), true, "empty kinds dimmed, not clickable");
// matte status highlights: ink readable on each (WCAG ratio >= 7)
const ratios = await p.evaluate(() => {
  const lum = (c) => { const [r, g, b] = c.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  return [".heat__bad", ".heat__warn", ".heat__ok"].map((sel) => { const el = document.querySelector(sel); const cs = getComputedStyle(el); const a = lum(cs.backgroundColor), b = lum(cs.color); return +(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)).toFixed(2)); });
});
for (const x of ratios) assert.ok(x >= 7, `highlight contrast ${x}`);
console.log(`    highlight contrast red/ochre/green: ${ratios.join(" / ")}`);
await p.locator(".tally__cell", { hasText: "Matches" }).click();
assert.match(await p.locator(".problem.is-selected").innerText(), /750 ml/, "a tile jumps to its first finding");
assert.equal(await p.locator(".tally__cell", { hasText: "Matches" }).getAttribute("aria-pressed"), "true");
for (const w of [1440, 390]) { await p.setViewportSize({ width: w, height: w > 500 ? 900 : 844 }); await p.waitForTimeout(300); await noScroll(w); await p.screenshot({ path: `qa/out/polish-review-${w}.png`, fullPage: true }); }
await p.setViewportSize({ width: 1440, height: 900 });
console.log("ok  review tally: counts per kind with the chip words, dismissed counted, tile selects its first finding");

// 4) "AI is working" on the draft check (response held open)
await p.route(`${API}/api/reviews`, async (r) => (r.request().method() === "POST" ? new Promise(() => {}) : r.continue()));
await p.goto(`${WEB}/app/draft`); await p.waitForSelector(".draft__text");
await p.fill(".draft__text", "Lumen Pods last 24 hours."); await p.click("button[type=submit]");
await p.waitForSelector(".thinking[role=status]");
assert.match(await p.locator(".thinking").innerText(), /Checking your draft/);
await p.waitForTimeout(900); await p.locator(".thinking").screenshot({ path: "qa/out/polish-thinking.png" });
console.log("ok  'AI is working' state while the draft is checked (role=status, roller animation)");

// 5) every workspace page: no horizontal scroll at 390, nav fits, no errors
await p.unroute(`${API}/api/reviews`);
for (const path of ["/app/sources", "/app/queue", "/app/insights", "/app/guidelines", "/app/rules", "/app/scorecard", "/app/record"]) {
  for (const w of [1440, 390]) {
    await p.setViewportSize({ width: w, height: w > 500 ? 900 : 844 }); await p.goto(WEB + path, { waitUntil: "networkidle" }); await p.waitForTimeout(500);
    await noScroll(w);
    if (w === 390) for (const s of await p.locator(".track__stage").all()) { const bb = await s.boundingBox(); assert.ok(bb.x >= 0 && bb.x + bb.width <= 390, `${path}: stage visible at 390`); }
  }
}
console.log("ok  7 workspace pages: no horizontal scroll at 390, all five stages on screen");

// 6) reduced motion: nothing moves
const rm = await b.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
await rm.goto(`${WEB}/login?next=%2Fapp%2Fdraft`, { waitUntil: "networkidle" });
await rm.fill("#a-email", "ben@seed.inkloom.demo"); await rm.fill("#a-password", process.env.AUDIT_PASSWORD); await rm.click("button[type=submit]");
await rm.waitForURL("**/app/draft"); await rm.waitForSelector(".track__tile");
const anim = await rm.evaluate(() => [".app__light", ".stage-head__title", ".panel"].map((s) => getComputedStyle(document.querySelector(s)).animationName));
assert.deepEqual(anim, ["none", "none", "none"]);
assert.equal(await rm.locator(".track__tile").evaluate((el) => getComputedStyle(el).transitionDuration), "0s");
console.log("ok  reduced motion: light, title and panel animations off; tile doesn't slide");
assert.deepEqual(errors, []); console.log("ok  no page errors"); await b.close(); process.exit(0);
