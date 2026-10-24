// Dismiss / comments / server-side Intent-lock against the REAL backend, as a seeded user.
// No AI key is needed: brand-rule findings are real without a model. Setup (API): a prohibited-term
// rule "guaranteed" -> "designed", then one review. Locking "guaranteed" AFTER the review ran makes
// the stored rule suggestion a real withheld_by_intent_lock case. Rules are removed at the end.
// AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/dismiss-comments-locks.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const WEB = "http://localhost:3000", API = "http://localhost:8000";
const EMAIL = process.env.AUDIT_EMAIL ?? "ben@seed.inkloom.demo";
const TEXT = "Our Lumen Pods are guaranteed to keep music going all day. Lumen Pods cost ₹2,499.";

async function call(token, method, path, body, extra = {}) {
  const res = await fetch(`${API}${path}`, { method, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...extra }, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: res.status, json: await res.json().catch(() => null) };
}
const login = await (await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: EMAIL, password: process.env.AUDIT_PASSWORD }) })).json();
const token = login.access_token ?? login.token;
assert.ok(token, "signed in through the API");
const [brand] = (await call(token, "GET", "/api/brands")).json;
const rules = await call(token, "PUT", `/api/brands/${brand.id}/rules`, { rules: { prohibited_terms: [{ rule_id: "no-guarantee", term: "guaranteed", approved_alternative: "designed", severity: "high" }] } });
assert.equal(rules.status, 200, JSON.stringify(rules.json));
const created = await call(token, "POST", "/api/reviews", { brand_id: brand.id, title: "Dismiss/lock test", text: TEXT }, { "Idempotency-Key": `qa-dcl-${Date.now()}` });
assert.equal(created.status, 201, JSON.stringify(created.json));
const review = created.json;
const ruleFinding = review.findings.find((f) => f.check_type === "rule" && f.original_text.toLowerCase() === "guaranteed");
assert.ok(ruleFinding, "real rule finding");
console.log(`    setup: review ${review.status}, ${review.findings.length} findings, rule suggestion "${ruleFinding.suggested_correction}"`);

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = []; p.on("pageerror", (e) => errors.push(e.message));
const shot = async (name) => {
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    await p.setViewportSize({ width: w, height: h });
    await p.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); }); await p.waitForTimeout(200);
    const sw = await p.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(sw <= w, `${name} @${w}: horizontal scroll (${sw}px)`);
    await p.screenshot({ path: `qa/out/dcl-${name}-${w}.png`, fullPage: true });
  }
  await p.setViewportSize({ width: 1440, height: 900 });
};
await p.goto(`${WEB}/login?next=${encodeURIComponent(`/app/review?id=${review.id}`)}`, { waitUntil: "networkidle" });
await p.fill("#a-email", EMAIL); await p.fill("#a-password", process.env.AUDIT_PASSWORD); await p.click("button[type=submit]");
await p.waitForURL(`**/app/review?id=${review.id}`, { timeout: 20000 }); await p.waitForSelector(".problem");

// ---- Decide before dismissing: Approve state and status
await p.goto(`${WEB}/app/decide?id=${review.id}`); await p.waitForSelector(".rows");
const approve = p.getByRole("button", { name: /^Approve/ });
const approveBefore = await approve.isDisabled();
const decideStatusBefore = await p.locator(".stage-head__status").innerText();

// ---- 1) Dismiss with a note (Review page, keyboard-only)
await p.goto(`${WEB}/app/review?id=${review.id}`); await p.waitForSelector(".problem");
const statusBefore = await p.locator(".stage-head__status").innerText();
const row = p.locator(".problem", { hasText: "Terminology rule" }).first();
await row.focus(); await p.keyboard.press("Enter");
const note = p.getByLabel("Note (optional)");
await note.focus(); await p.keyboard.type("We say this in the US ad");
await p.keyboard.press("Tab");
assert.equal(await p.evaluate(() => document.activeElement?.textContent), "Dismiss this finding", "Tab reaches the Dismiss button");
const focusRing = await p.evaluate(() => getComputedStyle(document.activeElement).outlineStyle);
assert.notEqual(focusRing, "none", "visible focus on the Dismiss button");
await p.keyboard.press("Enter");
await p.waitForSelector("text=Dismissed by you on", { timeout: 8000 }).catch(async (e) => {
  console.log("DEBUG section:", await p.locator("section[aria-label='Dismiss this finding']").innerText());
  throw e;
});
assert.match(await row.innerText(), /§ Terminology rule[\s\S]*⊖\s*Dismissed/, "verdict chip kept, Dismissed badge added");
assert.equal(await p.locator(".add-heat-dismissed").count() >= 1, true, "highlighted draft shows Dismissed");
assert.equal(await p.locator(".stage-head__status").innerText(), statusBefore, "review status unchanged");
console.log("ok  dismissed with a note (keyboard): verdict chip kept + '⊖ Dismissed' in list and draft; review status unchanged");

await p.reload({ waitUntil: "networkidle" }); await p.locator(".problem", { hasText: "Terminology rule" }).first().click();
const detail = await p.locator("section[aria-label='Dismiss this finding']").innerText();
assert.match(detail, /Dismissed by you on[\s\S]*Note: We say this in the US ad[\s\S]*Restore/);
await shot("dismissed");
console.log("ok  after reload: still dismissed, note shown, Restore offered");

// ---- Decide after dismissing: unchanged guards, counts, badge
await p.goto(`${WEB}/app/decide?id=${review.id}`); await p.waitForSelector(".rows");
assert.equal(await approve.isDisabled(), approveBefore, "Approve state unchanged by dismissing");
assert.equal(await p.locator(".stage-head__status").innerText(), decideStatusBefore);
const found = await p.locator(".panel").first().innerText();
assert.match(found, /\d+ open, 1 dismissed/);
assert.match(found, /⊖\s*Dismissed/);
console.log(`ok  decide: '${found.match(/\d+ open, 1 dismissed/)[0]}', badge shown, Approve ${approveBefore ? "disabled" : "enabled"} before and after`);

// ---- Restore, then a real 409 (dismissed elsewhere while this page is open)
await p.goto(`${WEB}/app/review?id=${review.id}`); await p.locator(".problem", { hasText: "Terminology rule" }).first().click();
await p.getByRole("button", { name: "Restore" }).click();
await p.getByRole("button", { name: "Dismiss this finding" }).waitFor();
assert.doesNotMatch(await p.locator(".problem", { hasText: "Terminology rule" }).first().innerText(), /Dismissed/);
const elsewhere = await call(token, "POST", `/api/findings/${ruleFinding.finding_id}/dismiss`, {});
assert.equal(elsewhere.status, 201);
await p.getByRole("button", { name: "Dismiss this finding" }).click();
await p.waitForSelector("section[aria-label='Dismiss this finding'] .app-alert--bad");
assert.equal(await p.locator("section[aria-label='Dismiss this finding'] .app-alert--bad").innerText(), "this finding is already dismissed");
assert.ok(await p.getByRole("button", { name: "Dismiss this finding" }).isVisible(), "old state kept, nothing optimistic");
await call(token, "POST", `/api/findings/${ruleFinding.finding_id}/restore`, {});
console.log("ok  restore works; a second dismiss shows the backend's 409 as-is ('this finding is already dismissed') and keeps the old state");

// ---- 2) Comments (keyboard), plain text
await p.reload({ waitUntil: "networkidle" }); await p.locator(".problem", { hasText: "Terminology rule" }).first().click();
await p.waitForSelector("text=No comments yet");
const box = p.getByLabel("Add a comment");
const add = p.getByRole("button", { name: "Add comment" });
assert.equal(await add.isDisabled(), true, "disabled while blank");
await box.focus(); await p.keyboard.type("Check with legal.");
await p.keyboard.press("Tab"); await p.keyboard.press("Enter");
await p.waitForSelector(".add-comment");
const xss = "<script>window.__xss=1</script>\nLegal says fine.";
await box.fill(xss); await add.click();
await p.waitForFunction(() => document.querySelectorAll(".add-comment").length === 2);
assert.match(await p.locator("[aria-live=polite]", { hasText: "Comment added" }).innerText(), /Comment added/);
await p.reload({ waitUntil: "networkidle" }); await p.locator(".problem", { hasText: "Terminology rule" }).first().click();
await p.waitForFunction(() => document.querySelectorAll(".add-comment").length === 2);
const bodies = await p.locator(".add-comment__body").allInnerTexts();
assert.deepEqual(bodies, ["Check with legal.", xss], "oldest first, text as typed (line break kept)");
assert.equal(await p.locator(".add-comment script").count(), 0); assert.equal(await p.evaluate(() => window.__xss), undefined);
assert.match(await p.locator(".add-comment").first().innerText(), /^You · /i);
assert.match(await p.locator(".problem", { hasText: "Terminology rule" }).first().innerText(), /2 comments/i);
assert.equal(await p.locator(".add-comment__body").nth(1).evaluate((el) => getComputedStyle(el).whiteSpace), "pre-wrap");
await shot("comments");
console.log("ok  comments: two added (one by keyboard), oldest first after reload, '2 comments' in the list, <script> rendered as text");

// ---- 3) Intent-lock in the editor
await p.goto(`${WEB}/app/review-edit?id=${review.id}`); await p.waitForSelector(".add-editor__text");
assert.match(await p.locator(".add-editor").innerText(), /Saved to your account\. Suggested wording that would remove a protected phrase is never offered\./);
const select = (phrase) => p.locator(".add-editor__text").evaluate((el, ph) => { const at = el.value.indexOf(ph); el.focus(); el.setSelectionRange(at, at + ph.length); }, phrase);
let puts = 0; p.on("request", (r) => r.url().includes("/locks") && r.method() === "PUT" && puts++);
await select("₹2,499"); await p.getByRole("button", { name: "🔒 Mark must-keep text" }).click();
await p.waitForSelector(".add-lock:has-text('₹2,499')");
await select("guaranteed"); await p.getByRole("button", { name: "🔒 Mark must-keep text" }).click();
await p.waitForSelector(".add-lock:has-text('guaranteed')");
assert.equal(puts, 2);
assert.deepEqual((await call(token, "GET", `/api/content-versions/${review.content_version_id}/locks`)).json.locked_phrases, ["₹2,499", "guaranteed"]);
assert.equal(await p.evaluate(() => Object.keys(localStorage).filter((k) => k.includes("locks")).length), 0, "nothing in localStorage");
// 422 from the server: shown as-is, no local-only lock
const long = "x".repeat(201);
await p.locator(".add-editor__text").fill(`${TEXT} ${long}`); await select(long);
await p.getByRole("button", { name: "🔒 Mark must-keep text" }).click();
await p.waitForSelector(".app-alert--bad:has-text('Not saved')");
assert.match(await p.locator(".app-alert--bad", { hasText: "Not saved" }).innerText(), /Not saved: a locked phrase may be at most 200 characters/);
assert.equal(await p.locator(".add-lock").count(), 2, "failed PUT keeps no local lock");
console.log("ok  locks saved via PUT (server has them, nothing in localStorage); a 422 shows the backend message and keeps no local lock");

await p.reload({ waitUntil: "networkidle" }); await p.waitForSelector(".add-lock");
assert.deepEqual(await p.locator(".add-lock").allInnerTexts().then((t) => t.map((x) => x.replace(/🔒|×/g, "").trim())), ["₹2,499", "guaranteed"]);
await p.locator(".add-finding", { hasText: "Terminology rule" }).click();
const withheld = await p.locator(".add-suggest").innerText();
assert.match(withheld, /A suggestion was hidden because it would remove a protected phrase\. Check again to get one that keeps it\./);
assert.ok(await p.locator(".add-suggest").getByRole("button", { name: /Check again/ }).isVisible());
const served = (await call(token, "GET", `/api/reviews/${review.id}`)).json.findings.find((f) => f.finding_id === ruleFinding.finding_id);
assert.equal(served.withheld_by_intent_lock, true); assert.equal(served.suggested_correction, null);
await shot("editor-locks");
await shot("withheld");
console.log("ok  after reload: locks come from the server; the real withheld_by_intent_lock finding shows the hidden-suggestion note + Check again");

// Save as new version: inherited locks
await p.locator(".add-editor__text").fill(TEXT.replace("all day", "for hours"));
await p.getByRole("button", { name: "Save as new version" }).click();
await p.waitForSelector("text=/Saved as version \\d+/", { timeout: 90000 });
const items = await call(token, "GET", `/api/content/${review.content_item_id}/history`);
const newest = items.json.versions.find((v) => v.is_current);
assert.deepEqual((await call(token, "GET", `/api/content-versions/${newest.id}/locks`)).json.locked_phrases, ["₹2,499", "guaranteed"], "inherited on the server");
assert.equal(await p.locator(".add-lock").count(), 2, "editor shows the new version's locks");
console.log(`ok  saved version ${newest.version_number}: it inherited both locks (server) and the editor shows them`);

// Check again: no suggestion removes a lock
await p.getByRole("button", { name: /Check version \d+ again/ }).click();
await p.waitForSelector("text=/Checked again:/", { timeout: 90000 });
const latest = (await call(token, "GET", `/api/reviews?limit=1`)).json[0];
for (const f of latest.findings) for (const s of [f.suggested_correction, f.safer_wording].filter(Boolean))
  for (const l of ["₹2,499", "guaranteed"]) assert.ok(!f.original_text.includes(l) || s.includes(l), `suggestion keeps ${l}`);
const again = latest.findings.find((f) => f.check_type === "rule" && f.original_text.toLowerCase() === "guaranteed");
console.log(`ok  re-check: no suggestion removes a locked phrase (rule finding suggestion: ${JSON.stringify(again?.suggested_correction ?? null)}, withheld ${again?.withheld_by_intent_lock})`);

// ---- keyboard: no trap across the editor
const seen = new Set();
for (let i = 0; i < 80; i++) { await p.keyboard.press("Tab"); seen.add(await p.evaluate(() => document.activeElement?.outerHTML.slice(0, 80))); }
assert.ok(seen.size > 15, `focus moves through the page (${seen.size} distinct stops), no trap`);
console.log(`ok  keyboard: Tab moves through ${seen.size} distinct stops in the editor, no trap`);

await call(token, "PUT", `/api/brands/${brand.id}/rules`, { rules: null });
assert.deepEqual(errors, []); console.log("ok  rules removed again; no page errors"); await b.close();
