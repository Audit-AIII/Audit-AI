// Coverage page. Live placeholder review (must show no percentage), then ONE served review with
// real-shaped findings (the local backend has no AI key). AUDIT_PASSWORD=... REVIEW_ID=... node qa/coverage-live.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const { AUDIT_PASSWORD: password, REVIEW_ID: liveId } = process.env;
const WEB = "http://localhost:3000";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const errors = [];
p.on("pageerror", (e) => errors.push(e.message));
await p.goto(`${WEB}/login?next=${encodeURIComponent(`/app/coverage?id=${liveId}`)}`, { waitUntil: "networkidle" });
await p.fill("#a-email", "admin@seed.inkloom.demo");
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/coverage?id=*", { timeout: 20000 });
await p.waitForSelector(".app-alert--placeholder");
assert.equal(await p.locator(".add-coverage__pct").count(), 0, "no coverage number for a placeholder");
console.log("ok  live placeholder review: no coverage shown, labelled placeholder");

const T = "Meet the Aero 🎧 earbuds. One charge lasts 24 hours. They cost ₹2,499. Made from 90% recycled plastic. Order today.";
const cp = (s) => Array.from(s).length;
const span = (n) => ({ start: cp(T.slice(0, T.indexOf(n))), end: cp(T.slice(0, T.indexOf(n))) + cp(n) });
const f = (id, t, st, ev = []) => ({ finding_id: id, category: "product_claim", severity: "medium", original_text: t, span: span(t), check_type: "retrieval",
  explanation: `${st} test`, verification_status: st, suggested_correction: null, requires_human_review: st !== "supported", evidence: ev });
const fake = { id: "cov-fake", content_version_id: "cv", status: "needs_human_review", report_status: null,
  engine: { provider: "openrouter", model_id: "test", prompt_version: "v", contract_version: "0.1.0" }, error_summary: null, served_from_cache: false,
  started_at: null, completed_at: null, created_at: "2026-10-23T10:00:00Z", updated_at: "2026-10-23T10:00:00Z", required_reviewer_role: "brand_manager",
  content_item_id: null, brand_id: null, title: "Aero launch", version_number: 1, text: T,
  findings: [
    f("a", "One charge lasts 24 hours.", "contradicted", [{ id: "e", source_id: "s", source_version_id: "v", quote: "Battery life: 12 hours", relation: "contradicts" }]),
    f("b", "They cost ₹2,499.", "supported", [{ id: "e2", source_id: "s", source_version_id: "v", quote: "Price: ₹2,499", relation: "supports" }]),
    f("c", "Made from 90% recycled plastic.", "unverified"),
  ] };
await p.route("http://localhost:8000/api/reviews/cov-fake", (r) =>
  r.fulfill({ status: 200, contentType: "application/json", headers: { "Access-Control-Allow-Origin": WEB }, body: JSON.stringify(fake) }));
await p.goto(`${WEB}/app/coverage?id=cov-fake`, { waitUntil: "networkidle" });
await p.waitForSelector(".add-coverage__pct");
assert.equal(await p.locator(".add-coverage__pct").innerText(), "33%");
const labels = await p.locator(".add-sentence").evaluateAll((els) => els.map((e) => e.className.match(/add-sentence--(\w+)/)[1]));
assert.deepEqual(labels, ["none", "bad", "ok", "warn", "none"]);
assert.match(await p.locator(".add-window").first().innerText(), /Battery life: 12 hours/);
await p.locator(".add-sentence").nth(3).click();
assert.match(await p.locator(".panel").nth(1).innerText(), /No approved document covers this claim/);
await p.screenshot({ path: "qa/out/add-coverage-findings.png" });
console.log("ok  33% = 1 supported of 3 claim sentences; statuses none/contradicted/supported/unverified/none; click shows evidence");
assert.deepEqual(errors, []);
console.log("ok  no page errors");
await b.close();
