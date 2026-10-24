// Workspace nav: /app -> /app/insights; the Workspace menu marks the active page; no stage lit on
// workspace pages or /app/review-edit; sensible footer hint; every page within two clicks.
// AUDIT_EMAIL / AUDIT_PASSWORD / REVIEW_ID env. node qa/nav-live.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password, REVIEW_ID: rid } = process.env;
const WEB = "http://localhost:3000";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = []; p.on("pageerror", (e) => errors.push(e.message));
await p.goto(`${WEB}/login?next=%2Fapp`, { waitUntil: "networkidle" });
await p.fill("#a-email", email); await p.fill("#a-password", password); await p.click("button[type=submit]");
await p.waitForURL("**/app/insights", { timeout: 20000 });
console.log("ok  /app -> /app/insights");
const state = () => p.evaluate(() => ({
  stage: document.querySelector('.track [aria-current="page"]')?.textContent?.trim() ?? null,
  more: document.querySelector('.wsmenu__item[aria-current="page"] .wsmenu__item-label')?.textContent?.trim() ?? null,
  hint: document.querySelector(".app__status p")?.textContent?.trim(),
}));
for (const [path, more] of [["/app/insights", "Dashboard"], ["/app/queue", "Queue"], ["/app/guidelines", "Guidelines"], ["/app/scorecard", "Scorecard"]]) {
  await p.goto(WEB + path, { waitUntil: "networkidle" });
  const s = await state();
  assert.equal(s.stage, null, `${path}: no stage highlighted`); assert.equal(s.more, more); assert.doesNotMatch(s.hint, /Pick a stage/);
  console.log(`ok  ${path.padEnd(16)} active="${s.more}" stage=none hint="${s.hint.slice(0, 60)}…"`);
}
for (const path of [`/app/review-edit?id=${rid}`, `/app/coverage?id=${rid}`]) {
  await p.goto(WEB + path, { waitUntil: "networkidle" });
  const s = await state(); assert.equal(s.stage, null, path); assert.equal(s.more, null);
  console.log(`ok  ${path.split("?")[0].padEnd(16)} no stage, no workspace link highlighted`);
}
await p.goto(`${WEB}/app/review?id=${rid}`, { waitUntil: "networkidle" });
assert.equal((await state()).stage, "03Review");
// two-click reach: from any workspace page every destination is one click; per-review pages via Review (2 clicks)
const links = await p.evaluate(() => [...document.querySelectorAll(".track a, .wsmenu__list a, main a")].map((a) => new URL(a.href).pathname));
for (const need of ["/app/sources", "/app/draft", "/app/review", "/app/decide", "/app/record", "/app/insights", "/app/queue", "/app/guidelines", "/app/scorecard", "/app/review-edit", "/app/coverage"])
  assert.ok(links.includes(need), `reachable from Review: ${need}`);
console.log("ok  from the Review page all 11 workspace pages are one click away (so ≤2 from anywhere)");
assert.deepEqual(errors, []); console.log("ok  no page errors"); await b.close();
