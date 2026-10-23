// Review queue against the REAL backend: a draft sent from this browser appears as a real row
// (title, brand name, age, status) linking to the existing decide page; sample rows are labelled.
// AUDIT_PASSWORD=... node qa/queue-live.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const { AUDIT_PASSWORD: password } = process.env;
const WEB = "http://localhost:3000";
const b = await chromium.launch();
const errors = [];
for (const [w, h, tag] of [[1182, 937, "desktop"], [390, 844, "mobile"]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(`${WEB}/login?next=%2Fapp%2Fdraft`, { waitUntil: "networkidle" });
  await p.fill("#a-email", "admin@seed.inkloom.demo");
  await p.fill("#a-password", password);
  await p.click("button[type=submit]");
  await p.waitForURL("**/app/draft", { timeout: 20000 });
  await p.waitForFunction(() => /approved document/.test(document.querySelector(".brand-pill__id")?.textContent ?? ""));
  const title = `Queue test ${tag}`;
  await p.fill(".draft__text", "The Lumen Bottle keeps drinks cold for 24 hours.");
  await p.fill("input[placeholder^='e.g. Earbuds']", title);
  await p.click("button[type=submit]");
  await p.waitForURL("**/app/review?id=*", { timeout: 90000 });
  const id = new URL(p.url()).searchParams.get("id");
  await p.waitForSelector(".problem", { timeout: 30000 }); // the review page records it as "last review" once loaded
  await p.goto(`${WEB}/app/queue`, { waitUntil: "networkidle" });
  await p.waitForSelector(".add-table");
  const realPanel = p.locator(".panel").first();
  const row = realPanel.locator("tr", { hasText: title });
  await row.waitFor();
  assert.equal(await row.locator("a").getAttribute("href"), `/app/decide?id=${id}`);
  assert.match(await row.innerText(), /Lumen Goods \[seeded\][\s\S]*Brand manager|brand manager/i);
  assert.match(await realPanel.innerText(), /Needs backend/);
  assert.match(await p.locator(".panel").nth(1).innerText(), /Sample data[\s\S]*not counted/);
  assert.equal(await p.locator(".stage-head__status").count(), 0, "no count shown while the list route is missing");
  await p.screenshot({ path: `qa/out/add-queue-${tag}.png`, fullPage: tag === "mobile" });
  console.log(`ok  ${tag}: real row "${title}" -> /app/decide?id=…, brand by name, sample panel labelled; overflow=${await p.evaluate(() => document.documentElement.scrollWidth - innerWidth)}px`);
  await p.close();
}
assert.deepEqual(errors, []);
console.log("ok  no page errors");
await b.close();
