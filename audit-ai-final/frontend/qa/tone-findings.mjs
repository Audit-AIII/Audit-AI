// Brand voice findings: the API sends none today, so this first proves the real pages don't change,
// then adds example findings to the real response in the browser (nothing is stored; these examples
// exist only in this file) to see them rendered and hidden as the rule says.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/tone-findings.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";

const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "qa/out/tone-findings";
mkdirSync(OUT, { recursive: true });
const CORS = { "Access-Control-Allow-Origin": WEB, "Access-Control-Expose-Headers": "X-Request-ID" };

const login = await (
  await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "asha@seed.inkloom.demo", password }) })
).json();
const reviews = await (await fetch(`${API}/api/reviews?limit=100`, { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
const base = reviews.find((r) => r.status === "needs_human_review" && r.text);
assert.ok(reviews.every((r) => r.findings.every((f) => f.check_type !== "tone")), "the API sends no tone findings today; if this fails, test the real ones");
const session = { email: login.user.email, name: login.user.display_name, token: login.access_token, userId: login.user.id, organisation: login.organisation, role: login.role };

const word = base.text.split(" ").slice(0, 3).join(" ");
const example = (id, over) => ({
  finding_id: id,
  category: "brand_voice",
  severity: "low",
  original_text: word,
  span: { start: 0, end: [...word].length },
  check_type: "tone",
  explanation: "EXAMPLE explanation of why this breaks the guide.",
  verification_status: "not_applicable",
  suggested_correction: null,
  requires_human_review: true,
  evidence: [],
  guideline_source_id: "s",
  guideline_source_title: "EXAMPLE brand guide",
  guideline_source_version: "4",
  guideline_quote: "EXAMPLE passage from the guide.",
  alternative_wording: "EXAMPLE gentler wording",
  validation_status: "validated",
  comment_count: 0,
  ...over,
});

const b = await chromium.launch();
const open = async (path, findings, { width = 1182, height = 937 } = {}) => {
  const ctx = await b.newContext({ viewport: { width, height } });
  await ctx.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session));
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  if (findings)
    await p.route(`${API}/api/reviews/${base.id}`, (r) =>
      r.request().method() === "OPTIONS"
        ? r.continue()
        : r.fulfill({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ ...base, findings: [...base.findings, ...findings] }) }),
    );
  await p.goto(`${WEB}${path}?id=${base.id}`, { waitUntil: "networkidle" });
  await p.waitForTimeout(500);
  return { p, ctx, errors };
};
const main = (p) => p.locator("main").innerText();

// Today's real API: nothing about brand voice anywhere.
for (const path of ["/app/review", "/app/decide", "/app/record", "/app/coverage"]) {
  const { p, ctx, errors } = await open(path);
  assert.doesNotMatch(await main(p), /brand voice/i, path);
  assert.deepEqual(errors, [], path);
  await ctx.close();
}
console.log("ok  today's real pages show nothing about brand voice");

// With a validated passage: span, excerpt, explanation and a labelled, unapplied suggestion.
{
  const { p, ctx, errors } = await open("/app/review", [example("tone-ok", {})]);
  await p.locator('[data-finding="tone-ok"]').click();
  const detail = await p.locator(".add-detail").innerText();
  for (const expected of [/Brand voice/i, /EXAMPLE brand guide · version 4/i, /EXAMPLE passage from the guide/, /EXAMPLE explanation/, /EXAMPLE gentler wording/, /Suggested wording/i]) assert.match(detail, expected);
  assert.ok((await p.locator(".heat__mark.is-current").count()) > 0, "span marked in the draft");
  assert.match(await p.getByRole("region", { name: "What the checker found" }).innerText(), /1 brand voice finding/i);
  assert.doesNotMatch(await main(p), /hidden because/);
  assert.ok((await p.locator(".heat").innerText()).startsWith(word), "nothing applied to the draft");
  assert.deepEqual(errors, []);
  await p.screenshot({ path: `${OUT}/validated-desktop.png`, fullPage: true });
  await ctx.close();
  console.log("ok  validated finding renders like the rest of the product");
}

// No passage or a failed check: not on any page, and counted.
{
  const hidden = [example("no-quote", { guideline_quote: "" }), example("failed", { validation_status: "unsupported" })];
  for (const path of ["/app/review", "/app/decide", "/app/record", "/app/coverage"]) {
    const { p, ctx, errors } = await open(path, hidden);
    const text = await main(p);
    assert.doesNotMatch(text, /EXAMPLE/, `${path}: hidden content never shown`);
    if (path === "/app/review") {
      assert.match(text, /2 brand voice observations hidden because they cite no valid guideline passage/);
      await p.screenshot({ path: `${OUT}/hidden-desktop.png`, fullPage: true });
    }
    assert.deepEqual(errors, [], path);
    await ctx.close();
  }
  console.log("ok  unproven findings stay off every page, and are counted");
}

// Mixed list on a phone.
{
  const { p, ctx } = await open("/app/review", [example("tone-ok", {}), example("no-quote", { guideline_quote: null })], { width: 390, height: 844 });
  await p.locator('[data-finding="tone-ok"]').click();
  assert.equal(await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
  await p.screenshot({ path: `${OUT}/validated-mobile.png`, fullPage: true });
  await ctx.close();
  console.log("ok  phone width");
}
await b.close();
console.log("tone findings: all passed");
