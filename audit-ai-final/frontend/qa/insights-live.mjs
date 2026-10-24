// Dashboard: live brand-risk numbers (exact, with "Based on N reviews"); then one served response
// with category keys to check the plain-language labels. AUDIT_EMAIL / AUDIT_PASSWORD env.
import { chromium } from "playwright";
import assert from "node:assert/strict";
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password } = process.env;
const WEB = "http://localhost:3000", API = "http://localhost:8000";
const b = await chromium.launch();
const errors = [];
for (const [w, h, tag] of [[1440, 900, "desktop"], [390, 844, "mobile"]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  p.on("pageerror", (e) => errors.push(e.message));
  let live = null;
  p.on("response", async (r) => { if (r.url().includes("/api/analytics/brand-risk") && r.status() === 200 && !live) live = await r.json(); });
  await p.goto(`${WEB}/login?next=%2Fapp%2Finsights`, { waitUntil: "networkidle" });
  await p.fill("#a-email", email); await p.fill("#a-password", password); await p.click("button[type=submit]");
  await p.waitForURL("**/app/insights", { timeout: 20000 }); await p.waitForSelector(".add-insights__basis");
  assert.match(await p.locator(".add-insights__basis").innerText(), new RegExp(`Based on ${live.sample_size} review`));
  assert.equal(await p.locator(".app-alert--placeholder").count(), 0, "no sample data");
  await p.screenshot({ path: `qa/out/insights-live-${tag}.png`, fullPage: tag === "mobile" });
  console.log(`ok  ${tag}: live numbers, "Based on ${live.sample_size} reviews", no sample panels`);
  await p.route(`${API}/api/analytics/brand-risk**`, (r) => r.fulfill({ status: 200, contentType: "application/json", headers: { "Access-Control-Allow-Origin": WEB },
    body: JSON.stringify({ ...live, top_categories: [{ category: "contradicted_claim", count: 7 }, { category: "unsupported_claim", count: 4 }, { category: "engine_error", count: 1 }, { category: "brand_new_key", count: 2 }] }) }));
  await p.reload({ waitUntil: "networkidle" }); await p.waitForSelector(".add-bars");
  const t = await p.locator(".add-bars").innerText();
  for (const s of ["Claims that contradict your documents", "Claims with no evidence yet", "Could not be checked", "brand new key"]) assert.ok(t.includes(s), s);
  assert.doesNotMatch(t, /contradicted_claim|unsupported_claim/);
  await p.screenshot({ path: `qa/out/insights-labels-${tag}.png`, fullPage: tag === "mobile" });
  console.log(`ok  ${tag}: category keys shown in plain words, counts exact, unknown key falls back`);
  await p.close();
}
assert.deepEqual(errors, []); console.log("ok  no page errors"); await b.close();
