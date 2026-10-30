// Did a page drift from the Round 3 baseline? Retakes each route's screenshots and compares them pixel
// by pixel with .round3-baseline/ (grain is fixed, so a difference is a real one). Pages Round 3 changed
// on purpose are reported too, marked "expected". Needs the same seed as the baseline's run.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/round3-drift.mjs
import { chromium } from "playwright";
import { mkdirSync, readFileSync } from "node:fs";

const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "qa/out/round3-drift";
mkdirSync(OUT, { recursive: true });
const CHANGED = new Set(["review", "decide", "record", "queue", "scorecard"]);

const login = await (
  await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "asha@seed.inkloom.demo", password }) })
).json();
const reviews = await (await fetch(`${API}/api/reviews?limit=100`, { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
const id = (reviews.find((r) => r.status === "needs_human_review") ?? reviews[0]).id;
const session = { email: login.user.email, name: login.user.display_name, token: login.access_token, userId: login.user.id, organisation: login.organisation, role: login.role };
const ROUTES = [
  ["landing", "/", true, true],
  ["login", "/login", true],
  ["dashboard", "/app"],
  ["sources", "/app/sources"],
  ["draft", "/app/draft"],
  ["review", `/app/review?id=${id}`],
  ["review-edit", `/app/review-edit?id=${id}`],
  ["coverage", `/app/coverage?id=${id}`],
  ["decide", `/app/decide?id=${id}`],
  ["record", `/app/record?id=${id}`],
  ["queue", "/app/queue"],
  ["guidelines", "/app/guidelines"],
  ["rules", "/app/rules"],
  ["insights", "/app/insights"],
  ["scorecard", "/app/scorecard"],
];

const b = await chromium.launch();
const cmp = await b.newPage();
const diff = (a, c) =>
  cmp.evaluate(
    async ([x, y]) => {
      const load = (src) => new Promise((ok, no) => Object.assign(new Image(), { onload() { ok(this); }, onerror: no, src }));
      const [i, j] = await Promise.all([load(x), load(y)]);
      if (i.width !== j.width || i.height !== j.height) return { size: `${i.width}x${i.height} -> ${j.width}x${j.height}`, pct: null };
      const read = (img) => {
        const c2 = document.createElement("canvas");
        c2.width = img.width;
        c2.height = img.height;
        const g = c2.getContext("2d");
        g.drawImage(img, 0, 0);
        return g.getImageData(0, 0, img.width, img.height).data;
      };
      const [p, q] = [read(i), read(j)];
      let n = 0;
      for (let k = 0; k < p.length; k += 4) if (Math.abs(p[k] - q[k]) + Math.abs(p[k + 1] - q[k + 1]) + Math.abs(p[k + 2] - q[k + 2]) > 30) n++;
      return { size: null, pct: (100 * n) / (p.length / 4) };
    },
    [`data:image/png;base64,${a.toString("base64")}`, `data:image/png;base64,${c.toString("base64")}`],
  );

for (const [tag, width, height] of [["desktop", 1182, 937], ["mobile", 390, 844]]) {
  const signedIn = await b.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  await signedIn.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session));
  const signedOut = await b.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  for (const [slug, path, out, viewportOnly] of ROUTES) {
    const p = await (out ? signedOut : signedIn).newPage();
    await p.goto(`${WEB}${path}`, { waitUntil: "networkidle", timeout: 120000 });
    await p.evaluate(() => document.fonts.ready);
    await p.waitForTimeout(1500);
    const now = await p.screenshot({ path: `${OUT}/${slug}-${tag}.png`, fullPage: !viewportOnly });
    const r = await diff(readFileSync(`.round3-baseline/${slug}-${tag}.png`), now);
    const what = r.size ? `size ${r.size}` : `${r.pct.toFixed(2)}% pixels differ`;
    console.log(`${tag.padEnd(8)}${slug.padEnd(13)}${what}${CHANGED.has(slug) ? "  (expected: changed in Round 3)" : ""}`);
    await p.close();
  }
  await signedIn.close();
  await signedOut.close();
}
await b.close();
