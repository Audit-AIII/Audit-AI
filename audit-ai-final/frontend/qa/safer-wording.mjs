// safer_wording + conflicting_sources (Darsh's API change). Signs in for real, then serves ONE review
// that has: unverified with safer_wording (new backend), unverified with suggested_correction only
// (older backend), conflicting_sources, and contradicted with an evidence-backed fix.
// AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/safer-wording.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const WEB = "http://localhost:3000", API = "http://localhost:8000";
const T = "The Verde lasts 48 hours. It is the best bottle in India. It holds 750 ml. It is made in Pune.";
const cp = (s) => Array.from(s).length;
const span = (n) => ({ start: cp(T.slice(0, T.indexOf(n))), end: cp(T.slice(0, T.indexOf(n))) + cp(n) });
const f = (id, text, status, extra = {}) => ({ finding_id: id, category: null, severity: "medium", original_text: text, span: span(text), check_type: "retrieval",
  explanation: `${status} test`, verification_status: status, suggested_correction: null, requires_human_review: status !== "supported", evidence: [],
  rule_id: null, rule_type: null, scope: null, suggestion_basis: null, source_ids: null, ...extra });
const review = {
  id: "safer-test", content_version_id: "cv", content_item_id: null, brand_id: null, title: "Safer wording test", version_number: 1, text: T,
  status: "needs_human_review", report_status: null, engine: { provider: "fallback", model_id: "test", prompt_version: "v", contract_version: "0.2.0" },
  error_summary: null, served_from_cache: false, required_reviewer_role: null, rules_status: "complete", rule_checks: [],
  started_at: null, completed_at: null, created_at: "2026-10-24T10:00:00Z", updated_at: "2026-10-24T10:00:00Z",
  findings: [
    f("a", "The Verde lasts 48 hours.", "contradicted", { suggested_correction: "The Verde lasts 24 hours.",
      evidence: [{ id: "e", source_id: "s", source_version_id: "v", quote: "Keeps drinks cold for 24 hours.", relation: "contradicts", source_title: "Verde Fact Sheet", source_version_number: 1 }] }),
    f("b", "It is the best bottle in India.", "unverified", { safer_wording: "It is a popular bottle in India.", suggested_correction: null }),
    f("c", "It holds 750 ml.", "conflicting_sources"),
    f("d", "It is made in Pune.", "unverified", { suggested_correction: "It is made in India." }), // older backend
  ],
};

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = []; p.on("pageerror", (e) => errors.push(e.message));
await p.route(`${API}/api/reviews/safer-test`, (r) => r.fulfill({ status: 200, contentType: "application/json", headers: { "Access-Control-Allow-Origin": WEB }, body: JSON.stringify(review) }));
await p.goto(`${WEB}/login?next=${encodeURIComponent("/app/review?id=safer-test")}`, { waitUntil: "networkidle" });
await p.fill("#a-email", "ben@seed.inkloom.demo"); await p.fill("#a-password", process.env.AUDIT_PASSWORD); await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=safer-test", { timeout: 20000 }); await p.waitForSelector(".problem");

const detail = async (needle) => { await p.locator(".problem", { hasText: needle }).first().click(); return p.locator(".finding-detail").innerText(); };
let d = await detail("best bottle");
assert.match(d, /Safer wording, not evidence-backed: “It is a popular bottle in India\.”/);
d = await detail("made in Pune");
assert.match(d, /Safer wording, not evidence-backed: “It is made in India\.”/, "older backend: softened text gets the same label");
d = await detail("48 hours");
assert.match(d, /We suggest \(backed by your documents\): “The Verde lasts 24 hours\.”/);
assert.match(await p.locator(".rows[aria-label='Problems']").innerText(), /Approved documents disagree, check which is correct/);
await p.locator(".problem", { hasText: "750 ml" }).first().click();
assert.match(await p.locator(".panel").nth(2).locator(".panel__title").innerText(), /Approved documents disagree/i);
await p.screenshot({ path: "qa/out/safer-review.png", fullPage: true });
console.log("ok  review: safer wording labelled (new + old backend), evidence-backed fix labelled, conflicting_sources wording");

await p.goto(`${WEB}/app/decide?id=safer-test`); await p.waitForSelector(".fixes");
const fixes = await p.locator(".fixes").innerText();
assert.match(fixes, /It is a popular bottle in India\.[\s\S]*Safer wording, not evidence-backed/i);
assert.match(fixes, /The Verde lasts 24 hours\.[\s\S]*backed by your documents/i);
console.log("ok  decide: each suggestion shows its label");

await p.goto(`${WEB}/app/review-edit?id=safer-test`); await p.waitForSelector(".add-editor__text");
await p.locator(".add-finding", { hasText: "best bottle" }).click();
assert.match(await p.locator(".add-suggest").innerText(), /Safer wording, not evidence-backed \(not applied\)/i);
await p.getByRole("button", { name: "Apply suggestion to my draft" }).click();
assert.match(await p.inputValue(".add-editor__text"), /It is a popular bottle in India\./);
console.log("ok  editor: safer wording labelled and applied only to the local draft on click");
assert.deepEqual(errors, []); console.log("ok  no page errors"); await b.close();
