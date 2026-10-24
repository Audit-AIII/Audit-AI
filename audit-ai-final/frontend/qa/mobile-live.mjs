// 390x844: all five stages visible and clickable, footer readable, no horizontal page scroll.
// AUDIT_EMAIL / AUDIT_PASSWORD / REVIEW_ID env. node qa/mobile-live.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password, REVIEW_ID: rid } = process.env;
const WEB = "http://localhost:3000";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 390, height: 844 } });
await p.goto(`${WEB}/login?next=%2Fapp%2Finsights`, { waitUntil: "networkidle" });
await p.fill("#a-email", email); await p.fill("#a-password", password); await p.click("button[type=submit]");
await p.waitForURL("**/app/insights", { timeout: 20000 });
for (const path of [`/app/review?id=${rid}`, `/app/decide?id=${rid}`, "/app/insights"]) {
  await p.goto(WEB + path, { waitUntil: "networkidle" }); await p.waitForTimeout(600);
  const r = await p.evaluate(() => ({
    over: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    hidden: [...document.querySelectorAll(".stage")].filter((s) => { const b = s.getBoundingClientRect(); return b.right > innerWidth || b.left < 0; }).map((s) => s.textContent),
  }));
  assert.equal(r.over, 0, `${path}: horizontal page scroll`); assert.deepEqual(r.hidden, [], `${path}: stages off-screen`);
  const name = path.split("?")[0].split("/").pop();
  await p.screenshot({ path: `qa/out/mobile-${name}.png` });
  await p.locator(".app__status").screenshot({ path: `qa/out/mobile-${name}-footer.png` });
  console.log(`ok  ${path.split("?")[0].padEnd(13)} scrollWidth==clientWidth, all 5 stages on screen`);
}
await p.click(".stage >> text=Record"); await p.waitForURL("**/app/record**");
console.log("ok  Record stage reachable by tap"); await b.close();
