// Round 3 polish sweep: every new or changed page at three sizes, in solo and team states. Reports
// axe violations, sideways scroll, small tap targets on phones, and layout shift, and checks that
// reduced motion stops the new animations. Team states use the contract examples, layered on in the browser.
// Screenshots: qa/out/round3-polish/. Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/round3-polish.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdirSync, readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "qa/out/round3-polish";
mkdirSync(OUT, { recursive: true });
const CORS = { "Access-Control-Allow-Origin": WEB, "Access-Control-Expose-Headers": "X-Request-ID" };
const json = (status, body) => ({ status, contentType: "application/json", headers: CORS, body: JSON.stringify(body) });
const fixture = (n) => JSON.parse(readFileSync(`qa/fixtures/${n}.json`, "utf8"));
const { id: _a, content_version_id: _b, content_item_id: _c, status: _d, title: _e, version_number: _f, ...team } = fixture("governance/governance_review_item_team_approver");

const login = await (
  await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "asha@seed.inkloom.demo", password }) })
).json();
const auth = { Authorization: `Bearer ${login.access_token}` };
const reviews = await (await fetch(`${API}/api/reviews?limit=100`, { headers: auth })).json();
const base = reviews.find((r) => r.status === "needs_human_review");
const id = base.id;
const session = { email: login.user.email, name: login.user.display_name, token: login.access_token, userId: login.user.id, organisation: login.organisation, role: login.role };

const asTeam = async (p) => {
  await p.route(`${API}/api/workspace/members`, (r) => r.fulfill(json(200, fixture("governance/governance_members"))));
  await p.route(`${API}/api/workspace/invitations`, (r) => r.fulfill(json(200, fixture("governance/governance_invitations_list"))));
  await p.route(`${API}/api/reviews/${id}`, (r) => (r.request().method() === "OPTIONS" ? r.continue() : r.fulfill(json(200, { ...base, ...team }))));
};
const withRun = (p) => p.route(`${API}/api/evaluations/latest`, (r) => r.fulfill(json(200, fixture("evaluation-run.api-example"))));
const partial = (p) => p.route(`${API}/api/reviews/${id}`, (r) => (r.request().method() === "OPTIONS" ? r.continue() : r.fulfill(json(200, { ...base, rules_status: "incomplete" }))));
const failed = (p) => p.route(`${API}/api/reviews/${id}`, (r) => (r.request().method() === "OPTIONS" ? r.continue() : r.fulfill(json(200, { ...base, status: "failed", findings: [], error_summary: "the provider did not answer" }))));

const PAGES = [
  { name: "review", path: `/app/review?id=${id}` },
  { name: "review-partial", path: `/app/review?id=${id}`, before: partial },
  { name: "review-failed", path: `/app/review?id=${id}`, before: failed },
  { name: "decide", path: `/app/decide?id=${id}` },
  { name: "decide-team", path: `/app/decide?id=${id}`, before: asTeam },
  { name: "queue", path: "/app/queue" },
  { name: "record", path: `/app/record?id=${id}` },
  { name: "scorecard-none", path: "/app/scorecard" },
  { name: "scorecard-run", path: "/app/scorecard", before: withRun },
  { name: "team", path: "/app/team" },
  { name: "team-full", path: "/app/team", before: asTeam },
  { name: "audit", path: "/app/audit" },
  { name: "invite-signed-out", path: "/invite/accept?token=abc", signedOut: true },
  { name: "invite-signed-in", path: "/invite/accept?token=abc" },
];
const SIZES = [
  { tag: "desktop", width: 1182, height: 937 },
  { tag: "tablet", width: 768, height: 1024 },
  { tag: "phone", width: 390, height: 844 },
];

const b = await chromium.launch();
const problems = [];
for (const s of SIZES) {
  for (const page of PAGES) {
    const ctx = await b.newContext({ viewport: { width: s.width, height: s.height } });
    if (!page.signedOut) await ctx.addInitScript((v) => window.localStorage.setItem("audit-ai.session", v), JSON.stringify(session));
    await ctx.addInitScript(() => {
      window.__cls = 0;
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value;
      }).observe({ type: "layout-shift", buffered: true });
    });
    const p = await ctx.newPage();
    const errors = [];
    p.on("pageerror", (e) => errors.push(e.message));
    await page.before?.(p);
    await p.goto(`${WEB}${page.path}`, { waitUntil: "networkidle", timeout: 120000 });
    await p.waitForTimeout(1200);
    await p.addScriptTag({ path: axePath });
    const axe = await p.evaluate(async () =>
      (await window.axe.run(document, { resultTypes: ["violations"] })).violations.map((v) => ({ id: v.id, impact: v.impact, n: v.nodes.length, targets: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) })),
    );
    const facts = await p.evaluate(() => {
      const small = [...document.querySelectorAll("main a, main button, main select, main input, main textarea, main summary")]
        .filter((el) => el.offsetParent !== null)
        .map((el) => ({ el, r: el.getBoundingClientRect() }))
        .filter(({ r }) => r.height > 0 && r.height < 44)
        .map(({ el, r }) => `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]} "${(el.textContent ?? "").trim().slice(0, 24)}" ${Math.round(r.height)}px`);
      return { overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth, small: [...new Set(small)], cls: window.__cls };
    });
    const line = [`${s.tag.padEnd(8)}${page.name.padEnd(19)}`];
    const serious = axe.filter((v) => v.impact === "serious" || v.impact === "critical");
    line.push(axe.length ? axe.map((v) => `${v.impact}:${v.id}(${v.n})`).join(" ") : "axe clean");
    line.push(`cls=${facts.cls.toFixed(3)}`);
    if (facts.overflow) line.push("SIDEWAYS SCROLL");
    if (errors.length) line.push(`ERRORS ${errors[0]}`);
    console.log(line.join(" | "));
    for (const v of serious) problems.push(`${s.tag} ${page.name}: ${v.id} -> ${v.targets.join(" | ")}`);
    if (facts.overflow) problems.push(`${s.tag} ${page.name}: sideways scroll`);
    if (errors.length) problems.push(`${s.tag} ${page.name}: ${errors[0]}`);
    if (s.tag === "phone" && facts.small.length) console.log(`        small tap targets: ${facts.small.join("; ")}`);
    await p.screenshot({ path: `${OUT}/${page.name}-${s.tag}.png`, fullPage: true });
    await ctx.close();
  }
}

// Reduced motion: the new animation stops.
{
  const ctx = await b.newContext({ viewport: { width: 1182, height: 937 }, reducedMotion: "reduce" });
  await ctx.addInitScript((v) => window.localStorage.setItem("audit-ai.session", v), JSON.stringify(session));
  const p = await ctx.newPage();
  await p.goto(`${WEB}/app/decide?id=${id}`, { waitUntil: "networkidle" });
  await p.waitForSelector(".add-gov");
  assert.equal(await p.locator(".add-gov").evaluate((el) => getComputedStyle(el).animationName), "none");
  await ctx.close();
  console.log("ok  reduced motion stops the new animation");
}
await b.close();
console.log(`\n${problems.length} problems`);
for (const x of problems) console.log(`  ${x}`);
