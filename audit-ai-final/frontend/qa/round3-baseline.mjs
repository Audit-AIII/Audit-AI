// Round 3 baseline: visits every route as a seeded user at 1182x937 and 390x844 and saves the "before"
// screenshots to .round3-baseline/, plus what each route called and any errors it hit, to
// .round3-baseline/routes.json. Needs the real backend (scripts/seed.py --reset) and `npm run dev`.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/round3-baseline.mjs
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const email = process.env.AUDIT_EMAIL ?? "asha@seed.inkloom.demo";
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = ".round3-baseline";
const VIEWPORTS = [
  { name: "desktop", width: 1182, height: 937 },
  { name: "mobile", width: 390, height: 844 },
];
mkdirSync(OUT, { recursive: true });

const login = await (
  await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) })
).json();
if (!login.access_token) throw new Error(`login failed: ${JSON.stringify(login)}`);
const reviews = await (await fetch(`${API}/api/reviews?limit=100`, { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
const id = (reviews.find((r) => r.status === "needs_human_review") ?? reviews[0]).id;

const ROUTES = [
  { slug: "landing", path: "/", viewportOnly: true },
  { slug: "login", path: "/login", signedOut: true },
  { slug: "dashboard", path: "/app" },
  { slug: "sources", path: "/app/sources" },
  { slug: "draft", path: "/app/draft" },
  { slug: "review", path: `/app/review?id=${id}` },
  { slug: "review-edit", path: `/app/review-edit?id=${id}` },
  { slug: "coverage", path: `/app/coverage?id=${id}` },
  { slug: "decide", path: `/app/decide?id=${id}` },
  { slug: "record", path: `/app/record?id=${id}` },
  { slug: "queue", path: "/app/queue" },
  { slug: "guidelines", path: "/app/guidelines" },
  { slug: "rules", path: "/app/rules" },
  { slug: "insights", path: "/app/insights" },
  { slug: "scorecard", path: "/app/scorecard" },
];

const session = {
  email,
  name: login.user.display_name,
  token: login.access_token,
  userId: login.user.id,
  organisation: login.organisation,
  role: login.role,
};

const browser = await chromium.launch();
const results = [];
for (const vp of VIEWPORTS) {
  const signedIn = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1 });
  await signedIn.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session));
  const signedOut = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1 });

  for (const route of ROUTES) {
    const page = await (route.signedOut ? signedOut : signedIn).newPage();
    const calls = new Set();
    const failedCalls = new Set();
    const pageErrors = [];
    const consoleErrors = [];
    page.on("response", (r) => {
      const url = r.url();
      if (!url.startsWith(API)) return;
      const call = `${r.request().method()} ${new URL(url).pathname}`;
      calls.add(call);
      if (r.status() >= 400) failedCalls.add(`${call} -> ${r.status()}`);
    });
    page.on("pageerror", (e) => pageErrors.push(e.message));
    page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text().slice(0, 200)));

    await page.goto(`${WEB}${route.path}`, { waitUntil: "networkidle", timeout: 120000 });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/${route.slug}-${vp.name}.png`, fullPage: !route.viewportOnly });

    const facts = await page.evaluate(() => ({
      h1: document.querySelector("h1")?.textContent?.trim() ?? null,
      alerts: [...document.querySelectorAll('[role="alert"]')].map((a) => a.textContent.trim().slice(0, 160)).filter(Boolean),
      overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));
    results.push({
      route: route.slug,
      path: route.path.replace(id, "<id>"),
      viewport: vp.name,
      finalPath: new URL(page.url()).pathname,
      ...facts,
      calls: [...calls].sort(),
      failedCalls: [...failedCalls].sort(),
      pageErrors,
      consoleErrors,
    });
    console.log(`${vp.name.padEnd(8)}${route.slug.padEnd(13)}h1=${facts.h1} calls=${calls.size} failed=${failedCalls.size} errors=${pageErrors.length} overflowX=${facts.overflowX}`);
    await page.close();
  }
  await signedIn.close();
  await signedOut.close();
}
await browser.close();
writeFileSync(`${OUT}/routes.json`, JSON.stringify(results, null, 2));
