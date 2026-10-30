// Are all the pages and links on point, and do frontend and backend agree? Three checks:
//  1. Every API path written in the frontend's code exists in the server's /openapi.json.
//  2. Opens every page, signed in and signed out, at both page sizes, and follows every internal link
//     it finds. Fails on a bad page, an uncaught error, a server error, or a failed API call.
//  3. Every API call the pages really make is a published route.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/route-crawl.mjs
import { chromium } from "playwright";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const problems = [];

const openapi = await (await fetch(`${API}/openapi.json`)).json();
const routes = Object.entries(openapi.paths).flatMap(([path, item]) => Object.keys(item).map((method) => ({ method: method.toUpperCase(), path, re: new RegExp(`^${path.replace(/\{[^}]+\}/g, "[^/]+")}$`) })));
const known = (path, method) => routes.some((r) => r.re.test(path) && (!method || r.method === method));

// 1. Paths in the code.
const walk = (dir) => readdirSync(dir).flatMap((n) => {
  const p = join(dir, n);
  return statSync(p).isDirectory() ? walk(p) : /\.tsx?$/.test(n) ? [p] : [];
});
const quoted = /["'`](\/api\/[^"'`\s]*)["'`]/g;
const inCode = new Map();
for (const file of ["lib", "app", "components"].flatMap(walk)) {
  for (const m of readFileSync(file, "utf8").matchAll(quoted)) {
    const path = m[1].replace(/\$\{[^}]*\}/g, "x").split("?")[0];
    if (!inCode.has(path)) inCode.set(path, file);
  }
}
// A helper may hold just the start of a path, such as /api/content/{id}, so a prefix of a route counts.
const isPrefix = (path) => routes.some((r) => r.path.replace(/{[^}]+}/g, "x").startsWith(`${path}/`));
for (const [path, file] of inCode) if (!known(path) && !isPrefix(path)) problems.push(`${file}: ${path} isn't a published route`);
console.log(`checked ${inCode.size} API paths written in the code`);

// Which published routes have no caller in the frontend? Reported, not a failure.
const covered = (r) => [...inCode.keys()].some((p) => r.re.test(p) || r.re.test(p.replace(/\/$/, "")));
const uncalled = routes.filter((r) => !covered(r) && !["/health"].includes(r.path));
console.log(`published routes with no literal path in the frontend (built from a shared prefix, or not used): ${uncalled.length}`);
for (const r of uncalled) console.log(`    ${r.method} ${r.path}`);

// 2 and 3. The pages.
const login = await (await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "asha@seed.inkloom.demo", password }) })).json();
const session = { email: login.user.email, name: login.user.display_name, token: login.access_token, userId: login.user.id, organisation: login.organisation, role: login.role };
const reviews = await (await fetch(`${API}/api/reviews?limit=100`, { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
const id = reviews.find((r) => r.status === "needs_human_review").id;
const START = ["/", "/login", "/login?mode=signup", "/invite/accept?token=crawl", "/app", "/app/sources", "/app/draft", `/app/review?id=${id}`, `/app/review-edit?id=${id}`, `/app/coverage?id=${id}`, `/app/decide?id=${id}`, `/app/record?id=${id}`, "/app/queue", "/app/guidelines", "/app/rules", "/app/insights", "/app/scorecard", "/app/team", "/app/audit", "/app/review", "/app/decide", "/app/record", "/app/coverage", "/app/review-edit"];
// Refusals the pages handle on purpose.
const EXPECTED_FAILURES = [/GET \/api\/evaluations\/latest -> 404/];

const b = await chromium.launch();
const calls = new Set();
for (const [who, signedIn] of [["signed in", true], ["signed out", false]]) {
  for (const [tag, width, height] of [["desktop", 1182, 937], ["phone", 390, 844]]) {
    const ctx = await b.newContext({ viewport: { width, height } });
    if (signedIn) await ctx.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session));
    const seen = new Set();
    const queue = [...START];
    let opened = 0;
    while (queue.length) {
      const path = queue.shift();
      const key = path.split("#")[0];
      if (seen.has(key)) continue;
      seen.add(key);
      const p = await ctx.newPage();
      const errors = [];
      p.on("pageerror", (e) => errors.push(e.message));
      p.on("response", (r) => {
        if (!r.url().startsWith(API)) return;
        const method = r.request().method();
        if (method === "OPTIONS") return;
        const apiPath = new URL(r.url()).pathname;
        calls.add(`${method} ${apiPath.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, "{id}")}`);
        if (!known(apiPath, method)) problems.push(`${path} called ${method} ${apiPath}, which isn't published`);
        const line = `${method} ${apiPath} -> ${r.status()}`;
        if (r.status() >= 400 && !EXPECTED_FAILURES.some((x) => x.test(line))) problems.push(`[${who}/${tag}] ${path}: ${line}`);
      });
      const res = await p.goto(`${WEB}${key}`, { waitUntil: "networkidle", timeout: 120000 });
      await p.waitForTimeout(250);
      opened++;
      if (!res || res.status() >= 400) problems.push(`[${who}/${tag}] ${key}: page answered ${res?.status()}`);
      if (errors.length) problems.push(`[${who}/${tag}] ${key}: ${errors[0]}`);
      if (await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)) problems.push(`[${who}/${tag}] ${key}: sideways scroll`);
      const missing = await p.evaluate(() => !document.querySelector("h1"));
      if (missing) problems.push(`[${who}/${tag}] ${key}: no page heading`);
      const links = await p.evaluate(() => [...document.querySelectorAll("a[href]")].map((a) => a.getAttribute("href")));
      for (const href of links) {
        if (!href?.startsWith("/") || href.startsWith("//")) continue;
        if (!seen.has(href.split("#")[0])) queue.push(href);
      }
      await p.close();
    }
    console.log(`${who}, ${tag}: opened ${opened} pages`);
    await ctx.close();
  }
}
await b.close();
console.log(`\nAPI calls the pages made (${calls.size}):`);
for (const c of [...calls].sort()) console.log(`    ${c}`);
console.log(`\n${problems.length} problems`);
for (const x of problems) console.log(`  ${x}`);
process.exit(problems.length ? 1 : 0);
