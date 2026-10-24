// axe-core scan (axe-core is already installed via eslint-plugin-jsx-a11y; no new dependency).
// Landing at 390px and 1440px, every /app page at both sizes. AUDIT_EMAIL / AUDIT_PASSWORD / REVIEW_ID env.
import { chromium } from "playwright";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password, REVIEW_ID: rid } = process.env;
const WEB = "http://localhost:3000";
const b = await chromium.launch();
const all = [];
async function scan(p, label) {
  await p.waitForLoadState("networkidle"); await p.waitForTimeout(900);
  await p.addScriptTag({ path: axePath });
  const r = await p.evaluate(async () => (await window.axe.run(document, { resultTypes: ["violations"] })).violations
    .map((v) => ({ id: v.id, impact: v.impact, n: v.nodes.length, targets: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) })));
  for (const v of r) all.push({ label, ...v });
  console.log(`${label.padEnd(30)} ${r.length ? r.map((v) => `${v.impact}:${v.id}(${v.n})`).join(" ") : "clean"}`);
}
for (const [w, h, tag] of [[390, 844, "390"], [1440, 900, "1440"]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  await p.goto(WEB, { waitUntil: "networkidle" });
  const H = await p.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y < H; y += 600) { await p.evaluate((y) => scrollTo(0, y), y); await p.waitForTimeout(80); }
  await scan(p, `landing @${tag}`);
  await p.goto(`${WEB}/login?next=%2Fapp%2Finsights`, { waitUntil: "networkidle" });
  await scan(p, `login @${tag}`);
  await p.fill("#a-email", email); await p.fill("#a-password", password); await p.click("button[type=submit]");
  await p.waitForURL("**/app/insights", { timeout: 20000 });
  for (const path of ["/app/insights", "/app/sources", "/app/draft", `/app/review?id=${rid}`, `/app/decide?id=${rid}`, `/app/record?id=${rid}`, "/app/queue", "/app/guidelines", "/app/scorecard", `/app/review-edit?id=${rid}`, `/app/coverage?id=${rid}`]) {
    await p.goto(WEB + path); await scan(p, `${path.split("?")[0]} @${tag}`);
  }
  await p.close();
}
const serious = all.filter((v) => v.impact === "serious" || v.impact === "critical");
console.log(`\n${all.length} violation groups, ${serious.length} serious/critical`);
for (const v of serious) console.log(`  ${v.label}: ${v.id} -> ${v.targets.join(" | ")}`);
await b.close();
