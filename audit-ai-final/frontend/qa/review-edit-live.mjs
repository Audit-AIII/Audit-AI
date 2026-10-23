// Correction editor. Part 1 is fully live: submit a draft, open the editor, save a new version
// (POST /api/content/{item}/versions), re-check (POST /api/reviews/{id}/rerun), newer-version notice.
// Part 2 serves ONE review with real-shaped findings (the local backend has no AI key, so it can
// only make placeholder reviews) to check suggestions, must-keep blocking and highlighting.
// AUDIT_PASSWORD=... node qa/review-edit-live.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const { AUDIT_PASSWORD: password } = process.env;
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const errors = [];
p.on("pageerror", (e) => errors.push(e.message));
const net = [];
p.on("response", (r) => {
  const u = new URL(r.url());
  if (u.port === "8000" && r.request().method() === "POST") net.push(`${r.request().method()} ${u.pathname.replace(/[0-9a-f-]{36}/g, "{id}")} ${r.status()}`);
});
const alert = () => p.locator(".app-alert").last().innerText();

await p.goto(`${WEB}/login?next=%2Fapp%2Fdraft`, { waitUntil: "networkidle" });
await p.fill("#a-email", "admin@seed.inkloom.demo");
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/draft", { timeout: 20000 });
await p.waitForFunction(() => /approved document/.test(document.querySelector(".brand-pill__id")?.textContent ?? ""));
const text = "The Lumen Bottle costs ₹1,499 and keeps drinks cold for 24 hours.";
await p.fill(".draft__text", text);
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=*", { timeout: 90000 });
const id = new URL(p.url()).searchParams.get("id");

// ---- Part 1: live ----
await p.goto(`${WEB}/app/review-edit?id=${id}`, { waitUntil: "networkidle" });
await p.waitForSelector(".add-editor__text");
assert.equal(await p.inputValue(".add-editor__text"), text, "draft prefilled with the review's text");
assert.match(await p.locator(".app-alert--placeholder").innerText(), /Placeholder review/);
await p.fill(".add-editor__text", text.replace("24 hours", "12 hours"));
assert.match(await p.locator(".add-diff").innerText(), /2412/);
await p.getByRole("button", { name: "Save as new version" }).click();
await p.waitForFunction(() => /Saved as version 2/.test(document.body.textContent ?? ""), null, { timeout: 90000 });
console.log("ok  live save:", await alert());
await p.getByRole("button", { name: /Check version 2 again/ }).click();
await p.waitForFunction(() => /Checked again/.test(document.body.textContent ?? ""), null, { timeout: 90000 });
console.log("ok  live re-check:", await alert());
await p.screenshot({ path: "qa/out/add-review-edit-live.png" });
// the original review now has a newer version
await p.goto(`${WEB}/app/review-edit?id=${id}`, { waitUntil: "networkidle" });
await p.waitForSelector(".add-editor__text");
await p.waitForFunction(() => /A newer version exists \(version 2\)/.test(document.body.textContent ?? ""), null, { timeout: 15000 });
console.log("ok  old review shows: A newer version exists (version 2)");
console.log("    requests:", net.join(" | "));

// ---- Part 2: findings UI (one served review) ----
const T = "Meet the Aero 🎧 earbuds, ₹2,499. One charge lasts 24 hours.";
const cp = (s) => Array.from(s).length;
const span = (n) => ({ start: cp(T.slice(0, T.indexOf(n))), end: cp(T.slice(0, T.indexOf(n))) + cp(n) });
const fake = {
  id: "fake-findings", content_version_id: "cv", status: "needs_human_review", report_status: null,
  engine: { provider: "openrouter", model_id: "test", prompt_version: "v", contract_version: "0.1.0" }, error_summary: null, served_from_cache: false,
  started_at: null, completed_at: null, created_at: "2026-10-23T10:00:00Z", updated_at: "2026-10-23T10:00:00Z", required_reviewer_role: "legal_reviewer",
  content_item_id: null, brand_id: null, title: "Aero launch", version_number: 1, text: T,
  findings: [
    { finding_id: "f1", category: "product_claim", severity: "high", original_text: "One charge lasts 24 hours.", span: span("One charge lasts 24 hours."), check_type: "retrieval",
      explanation: "The spec says 12 hours.", verification_status: "contradicted", suggested_correction: "One charge lasts 12 hours.", requires_human_review: true,
      evidence: [{ id: "e1", source_id: "s", source_version_id: "v", quote: "Battery life (single charge): 12 hours", relation: "contradicts" }] },
    { finding_id: "f2", category: "pricing", severity: "medium", original_text: "₹2,499", span: span("₹2,499"), check_type: "retrieval",
      explanation: "No approved source gives a price.", verification_status: "unverified", suggested_correction: "₹2,999", requires_human_review: true, evidence: [] },
  ],
};
await p.route(`${API}/api/reviews/fake-findings`, (r) =>
  r.fulfill({ status: 200, contentType: "application/json", headers: { "Access-Control-Allow-Origin": WEB }, body: JSON.stringify(fake) }),
);
await p.goto(`${WEB}/app/review-edit?id=fake-findings`, { waitUntil: "networkidle" });
await p.waitForSelector(".add-mark--bad");
assert.equal(await p.locator(".add-mark--bad").innerText(), "One charge lasts 24 hours.", "code-point span highlighted after an emoji");
assert.match(await p.locator(".add-window").innerText(), /Battery life \(single charge\): 12 hours/);
// lock the price, then try to apply the price suggestion -> blocked
await p.locator(".add-editor__text").evaluate((el) => {
  const at = el.value.indexOf("₹2,499");
  el.focus();
  el.setSelectionRange(at, at + "₹2,499".length);
});
await p.getByRole("button", { name: /Mark must-keep text/ }).click();
assert.match(await p.locator(".add-locks").innerText(), /₹2,499/);
await p.locator(".add-finding", { hasText: "₹2,499" }).click();
assert.equal(await p.getByRole("button", { name: "Apply suggestion to my draft" }).isDisabled(), true);
assert.match(await p.locator(".add-suggest").innerText(), /Blocked: would change “₹2,499”/);
console.log("ok  must-keep ₹2,499 blocks the price suggestion");
// battery suggestion applies to the local draft only
await p.locator(".add-finding", { hasText: "24 hours" }).click();
await p.getByRole("button", { name: "Apply suggestion to my draft" }).click();
assert.match(await p.inputValue(".add-editor__text"), /One charge lasts 12 hours\./);
assert.match(await p.inputValue(".add-editor__text"), /₹2,499/);
assert.match(await alert(), /Nothing is saved until you save a new version/);
assert.match(await p.locator(".add-needs").innerText(), /content_item_id/);
await p.screenshot({ path: "qa/out/add-review-edit-findings.png" });
console.log("ok  battery suggestion applied locally only; missing content_item_id shows a needs-backend note");

assert.deepEqual(errors, []);
console.log("ok  no page errors");
await b.close();
