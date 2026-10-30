// One real AI review, seen in the browser. Needs a server WITH a provider key, and uses a little of its
// quota: one short draft. Doesn't run an evaluation. Creates a throwaway e2e-* account.
// Usage: node qa/live-ai-check.mjs
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { randomUUID } from "node:crypto";

const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "qa/out/live-ai";
mkdirSync(OUT, { recursive: true });
const password = `live-check-${randomUUID().slice(0, 8)}`;
const post = async (path, token, body, headers = {}) => {
  const res = await fetch(`${API}${path}`, { method: "POST", headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers }, body: JSON.stringify(body) });
  return { status: res.status, body: await res.json() };
};

const email = `e2e-live-${Date.now()}@example.com`;
const me = (await post("/api/auth/register", null, { email, password, display_name: "Live Check" })).body;
const token = me.access_token;
const auth = { Authorization: `Bearer ${token}` };
const brand = (await (await fetch(`${API}/api/brands`, { headers: auth })).json())[0];
const form = new FormData();
form.append("file", new Blob(["Lumen Pods fact sheet. The Lumen Pods last 24 hours on one charge. They cost 2,499 rupees. They come in black and white."], { type: "text/plain" }), "facts.txt");
form.append("title", "Lumen Pods fact sheet");
form.append("sensitivity", "normal");
form.append("approve", "true");
const up = await fetch(`${API}/api/brands/${brand.id}/sources`, { method: "POST", headers: auth, body: form });
if (up.status !== 201) throw new Error(`upload: ${up.status} ${await up.text()}`);

// One claim the document contradicts, one it supports, one it doesn't cover.
const text = "The Lumen Pods last 40 hours on one charge. They cost 2,499 rupees. They are the best earbuds in India.";
const started = Date.now();
const { status, body: review } = await post("/api/reviews", token, { brand_id: brand.id, title: "Live AI check", text }, { "Idempotency-Key": randomUUID() });
console.log(`POST /api/reviews -> ${status} in ${Math.round((Date.now() - started) / 1000)}s`);
if (/^stub/i.test(review.engine?.provider ?? "")) {
  console.error("NOT A LIVE CHECK: this server has no AI provider, so the review is a placeholder. Set a key in services/api/.env (see AI_PROVIDER_KEYS.md), restart the API and run this again.");
  process.exit(2);
}
console.log(`status=${review.status} report_status=${review.report_status} engine=${JSON.stringify(review.engine)} error=${review.error_summary}`);
console.log(`risk=${review.risk_level} workflow=${review.workflow_status} counts=${JSON.stringify(review.summary_counts)}`);
console.log(`routing: ${review.routing_reason?.text}`);
for (const f of review.findings ?? []) {
  console.log(`- [${f.verification_status}/${f.severity}/${f.check_type}] "${f.original_text}"`);
  console.log(`    why: ${f.explanation}`);
  console.log(`    reasons: ${JSON.stringify(f.review_reasons)} evidence: ${JSON.stringify(f.evidence.map((e) => [e.relation, e.source_title, e.source_version_number, e.quote]))}`);
  console.log(`    correction: ${f.suggested_correction} | safer: ${f.safer_wording}`);
}

const b = await chromium.launch();
for (const [tag, width, height] of [["desktop", 1182, 937], ["phone", 390, 844]]) {
  const ctx = await b.newContext({ viewport: { width, height } });
  await ctx.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify({ email, name: "Live Check", token, userId: me.user.id, organisation: me.organisation, role: me.role, workspace: me.workspace }));
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(`${WEB}/app/review?id=${review.id}`, { waitUntil: "networkidle" });
  await p.waitForTimeout(1200);
  const first = review.findings?.find((f) => f.verification_status === "contradicted") ?? review.findings?.[0];
  if (first) await p.locator(`[data-finding="${first.finding_id}"]`).click();
  await p.waitForTimeout(800);
  console.log(`${tag}: page errors ${errors.length}; span notes ${await p.getByText("Span could not be located").count()}; marks ${await p.locator(".heat__mark").count()}`);
  await p.evaluate(() => window.scrollTo(0, 0));
  await p.screenshot({ path: `${OUT}/review-${tag}.png`, fullPage: true });
  await ctx.close();
}
await b.close();
