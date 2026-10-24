// Brand rules + rule findings against the REAL backend, as a seeded owner.
// Rules editor (save, 422 shown exactly, remove), then a draft that breaks the rules: rule chips (no
// claim verdict), whole-draft finding, suggestion label, rule-checks panel ("Not checked" never
// "Passed"), and the in-flight 409 retry. AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/rules-live.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const { AUDIT_PASSWORD: password } = process.env;
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
p.on("pageerror", (e) => errors.push(e.message));
const alert = () => p.locator(".app-alert").first().innerText();

await p.goto(`${WEB}/login?next=%2Fapp%2Frules`, { waitUntil: "networkidle" });
await p.fill("#a-email", process.env.AUDIT_EMAIL ?? "ben@seed.inkloom.demo");
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/rules", { timeout: 20000 });
await p.waitForSelector(".add-rules-json");

// start clean
if (await p.getByRole("button", { name: "Remove all rules" }).isEnabled()) {
  await p.getByRole("button", { name: "Remove all rules" }).click();
  await p.getByRole("button", { name: "Remove rules" }).click();
  await p.waitForFunction(() => /Rules removed/.test(document.body.innerText));
}

// 1) conflicting rules -> server 422 shown exactly
await p.fill(".add-rules-json", JSON.stringify({ prohibited_terms: [{ rule_id: "a", term: "Verde" }], required_terms: [{ rule_id: "b", term: "Verde" }] }, null, 2));
await p.getByRole("button", { name: "Save rules" }).click();
await p.waitForSelector(".app-alert--bad");
const shown = await alert();
assert.match(shown, /^invalid brand rules: .*conflicting rules: b requires a term that a prohibits$/);
console.log(`ok  422 shown exactly as returned: "${shown}"`);

// 2) quick add: prohibited "guaranteed" -> "designed"; required "Verde Bottles"; save
await p.getByRole("button", { name: "Undo changes" }).click();
await p.fill(".add-rules-json", "{}");
await p.fill("input[placeholder='e.g. guaranteed']", "guaranteed");
await p.fill("input[placeholder='e.g. designed']", "designed");
await p.selectOption("select >> nth=-1", "high");
await p.click("button:has-text('Add to the rules below')");
await p.selectOption("select >> nth=-2", "required_terms");
await p.fill("input[placeholder='e.g. Lumen Goods']", "Verde Bottles");
await p.click("button:has-text('Add to the rules below')");
let put = null;
p.on("request", (r) => r.url().endsWith("/rules") && r.method() === "PUT" && (put = JSON.parse(r.postData())));
await p.getByRole("button", { name: "Save rules" }).click();
await p.waitForFunction(() => /Saved as version/.test(document.body.innerText));
assert.ok(put.rules && !("rule_set_id" in put.rules) && !("version" in put.rules), "never sends rule_set_id / version");
assert.deepEqual(Object.keys(put.rules).sort(), ["prohibited_terms", "required_terms"]);
console.log(`ok  saved via PUT {rules} without rule_set_id/version; "${await alert()}"`);
await p.screenshot({ path: "qa/out/rules-editor.png", fullPage: true });

// 3) a draft that breaks both rules
await p.goto(`${WEB}/app/draft`);
await p.waitForFunction(() => /approved document/.test(document.querySelector(".brand-pill__id")?.textContent ?? ""));
await p.fill(".draft__text", "Our bottle is guaranteed to keep drinks cold all day.");
await p.fill("input[placeholder^='e.g. Earbuds']", "Rules test");
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=*", { timeout: 90000 });
const rid = new URL(p.url()).searchParams.get("id");
await p.waitForSelector(".rule-checks");
const review = await (await p.evaluate(async (id) => {
  const t = JSON.parse(localStorage.getItem("audit-ai.session")).token;
  return (await fetch(`http://localhost:8000/api/reviews/${id}`, { headers: { Authorization: `Bearer ${t}` } })).json();
}, rid));
const rules = review.findings.filter((f) => f.check_type === "rule");
console.log(`    live review: status=${review.status} rules_status=${review.rules_status} rule findings=${rules.map((f) => `${f.rule_type}/${f.scope}/${f.suggestion_basis}`).join(", ")}`);
assert.ok(rules.some((f) => f.rule_type === "prohibited_term"));
assert.ok(rules.some((f) => f.scope === "document"));
const list = await p.locator(".rows[aria-label='Problems']").innerText();
assert.match(list, /§ Terminology rule/);
assert.doesNotMatch(list, /No claim verdict/, "rule findings never show a claim verdict");
assert.match(list, /About the whole draft/);
assert.match(await p.locator(".whole-draft").innerText(), /Whole draft:/);
assert.equal(await p.locator(".heat__rule").count() >= 1, true, "prohibited term highlighted as a rule");
await p.locator(".problem", { hasText: "Prohibited term" }).first().click();
assert.match(await p.locator(".finding-detail").innerText(), /From brand rules: “designed”/);
const checks = await p.locator(".rule-checks").innerText();
assert.doesNotMatch(checks.match(/Image alt text[^\n]*\n?[^\n]*/)?.[0] ?? "", /Passed/);
assert.match(checks, /Not checked/);
for (const c of review.rule_checks.filter((c) => c.status === "not_checkable"))
  assert.ok(!(await p.locator(".rule-checks .rows__item", { hasText: c.reason ?? "" }).first().innerText()).includes("Passed"));
console.log(`ok  review: § rule chips, whole-draft finding, "From brand rules" label, ${review.rule_checks.filter((c) => c.status === "not_checkable").length} checks shown as "Not checked"`);
await p.screenshot({ path: "qa/out/rules-review.png", fullPage: true });

// 4) rules_status "incomplete" -> not shown as rule-clean, error_summary shown (one served response)
await p.route(`${API}/api/reviews/${rid}`, (r) => r.fulfill({ status: 200, contentType: "application/json", headers: { "Access-Control-Allow-Origin": WEB },
  body: JSON.stringify({ ...review, status: "completed", findings: [], engine: { provider: "fallback", model_id: "test", prompt_version: "v", contract_version: "0.2.0" }, rules_status: "incomplete", error_summary: "the accessibility checks failed to run" }) }));
await p.reload({ waitUntil: "networkidle" });
await p.waitForSelector(".app-alert--bad");
assert.match(await p.locator(".stage-head__status").innerText(), /rules not fully checked/i);
assert.match(await alert(), /didn’t finish[\s\S]*not shown as passing[\s\S]*accessibility checks failed to run/);
console.log("ok  rules_status incomplete: headline not rule-clean, error_summary shown");
await p.unroute(`${API}/api/reviews/${rid}`);

// 5) 409 "still being processed" is retried with the same key, not shown
let calls = 0;
const keys = [];
await p.route(`${API}/api/reviews`, async (r) => {
  if (r.request().method() !== "POST") return r.continue();
  calls++;
  keys.push(r.request().headers()["idempotency-key"]);
  if (calls === 1) return r.fulfill({ status: 409, contentType: "application/json", headers: { "Access-Control-Allow-Origin": WEB },
    body: JSON.stringify({ error: { code: "CONFLICT", message: "a request with this Idempotency-Key is still being processed", request_id: "x" } }) });
  return r.continue();
});
await p.goto(`${WEB}/app/draft`);
await p.waitForFunction(() => /approved document/.test(document.querySelector(".brand-pill__id")?.textContent ?? ""));
await p.fill(".draft__text", "Retry test. Verde Bottles keep drinks cold.");
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=*", { timeout: 90000 });
assert.equal(calls, 2); assert.equal(keys[0], keys[1]);
console.log("ok  409 'still being processed' retried once with the same Idempotency-Key, no error shown");
await p.unroute(`${API}/api/reviews`);

// 6) NUL character caught before sending
await p.goto(`${WEB}/app/draft`);
await p.waitForFunction(() => /approved document/.test(document.querySelector(".brand-pill__id")?.textContent ?? ""));
await p.locator(".draft__text").evaluate((el, v) => { const s = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set; s.call(el, v); el.dispatchEvent(new Event("input", { bubbles: true })); }, "bad\u0000text");
await p.click("button[type=submit]");
await p.waitForSelector(".app-alert--bad");
assert.match(await p.locator(".app-alert--bad").innerText(), /NUL character/);
console.log(`ok  NUL caught: "${await p.locator(".app-alert--bad").innerText()}"`);

// tidy: remove the rules again
await p.goto(`${WEB}/app/rules`); await p.waitForSelector(".add-rules-json");
await p.getByRole("button", { name: "Remove all rules" }).click(); await p.getByRole("button", { name: "Remove rules" }).click();
await p.waitForFunction(() => /Rules removed/.test(document.body.innerText));
assert.deepEqual(errors, []);
console.log("ok  rules removed again; no page errors");
await b.close();
