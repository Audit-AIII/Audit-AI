// Trust Scorecard: what the page says for each kind of result, from the API.md example run with
// GET /api/evaluations/latest answered in the browser. Never starts a run, so no provider is called.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/scorecard-states.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";

const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "qa/out/scorecard-states";
mkdirSync(OUT, { recursive: true });
const CORS = { "Access-Control-Allow-Origin": WEB, "Access-Control-Expose-Headers": "X-Request-ID" };
const json = (status, body) => ({ status, contentType: "application/json", headers: CORS, body: JSON.stringify(body) });
const example = JSON.parse(readFileSync("qa/fixtures/evaluation-run.api-example.json", "utf8"));

const login = await (
  await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "asha@seed.inkloom.demo", password }) })
).json();
const session = { email: login.user.email, name: login.user.display_name, token: login.access_token, userId: login.user.id, organisation: login.organisation, role: login.role };

const b = await chromium.launch();
const open = async (respond, { width = 1182, height = 937, before } = {}) => {
  const ctx = await b.newContext({ viewport: { width, height } });
  await ctx.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session));
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  let posted = 0;
  await p.route(`${API}/api/evaluations`, (r) => {
    posted++;
    return r.abort();
  });
  await before?.(p);
  if (respond) await p.route(`${API}/api/evaluations/latest`, respond);
  await p.goto(`${WEB}/app/scorecard`, { waitUntil: "networkidle" });
  await p.waitForTimeout(500);
  return { p, ctx, errors, posted: () => posted };
};
const withRun = (over) => (r) => r.fulfill(json(200, { ...example, ...over }));
const text = (p) => p.locator("main").innerText();

// The real API with no stored run: the published benchmark, saying what it is.
{
  const { p, ctx, errors } = await open();
  const published = JSON.parse(readFileSync("public/published-evaluation.json", "utf8"));
  const main = await text(p);
  assert.ok(main.includes(published.report_id), "the published report");
  assert.match(main, /replayed recording/i);
  assert.deepEqual(errors, []);
  await p.screenshot({ path: `${OUT}/published-desktop.png`, fullPage: true });
  await ctx.close();
  console.log("ok  no stored run shows the published benchmark");
}

// No stored run and no published file: Not evaluated, never a number.
{
  const { p, ctx, errors } = await open(undefined, { before: (page) => page.route("**/published-evaluation.json", (r) => r.fulfill({ status: 404, body: "" })) });
  assert.match(await text(p), /Not evaluated yet/i);
  assert.deepEqual(errors, []);
  await p.screenshot({ path: `${OUT}/none-desktop.png`, fullPage: true });
  await ctx.close();
  console.log("ok  no run reads Not evaluated");
}

// A full run: only the API's numbers, with denominators, date, config and limits.
{
  const { p, ctx, errors } = await open(withRun({}));
  const main = await text(p);
  for (const [k, s] of Object.entries(example.by_split)) {
    if (s.catch_rate.denominator) assert.ok(main.includes(`${s.catch_rate.numerator} of ${s.catch_rate.denominator} (`), `${k} catch counts`);
    if (s.false_positive_rate.denominator) assert.ok(main.includes(`${s.false_positive_rate.numerator} of ${s.false_positive_rate.denominator} (`), `${k} false-positive counts`);
  }
  assert.match(main, /Counts not supplied/);
  assert.match(main, /combine every split, across 80 labelled claims/);
  assert.match(main, /tuned on this data/i);
  assert.match(main, /How to read this/);
  for (const value of [example.dataset_version, example.engine_prompt_version, example.coverage, example.id]) assert.ok(main.includes(value), value);
  assert.ok(main.includes(example.limits_note.slice(0, 40)), "limits note");
  // Limits come before the numbers, without opening anything.
  assert.ok(main.indexOf(example.limits_note.slice(0, 40)) < main.indexOf("LATEST EVALUATION RUN"), "limits above the numbers");
  assert.ok((await p.locator('dd[title]').first().getAttribute("title")) === example.run_at, "raw date in the title");
  // absent_fact: null false-positive rate with claims measured.
  const row = p.getByRole("row").filter({ hasText: "absent fact" });
  assert.match(await row.innerText(), /Not evaluated/);
  assert.match(await row.innerText(), /100%/);
  assert.equal(await p.getByText("What do these mean?").count(), 1);
  await p.getByText("What do these mean?").click();
  assert.match(await text(p), /different from 0%/);
  assert.deepEqual(errors, []);
  await p.screenshot({ path: `${OUT}/run-desktop.png`, fullPage: true });
  await ctx.close();
  console.log("ok  full run");
}

// Missing vs zero: 0 stays 0%, null and n = 0 never become 0.
{
  const { p, ctx } = await open(
    withRun({
      catch_rate: null,
      false_positive_rate: 0,
      per_check: [{ check: "empty_check", catch_rate: 0.5, false_positive_rate: 0.5, n: 0 }, { check: "zero_check", catch_rate: 0, false_positive_rate: 0, n: 10 }],
      by_split: { dev: { n: 0, catch_rate: { numerator: 0, denominator: 0, value: null }, false_positive_rate: { numerator: 0, denominator: 8, value: 0 } } },
      latency_ms_p50: null,
      provider_failure_rate: null,
      engine_prompt_version: null,
    }),
  );
  const metrics = await p.locator(".add-metric").allInnerTexts();
  assert.match(metrics[0], /Not evaluated/);
  assert.match(metrics[1], /0%/);
  assert.doesNotMatch(metrics[0], /0%/);
  const empty = await p.getByRole("row").filter({ hasText: "empty check" }).innerText();
  assert.equal(empty.match(/Not evaluated/g)?.length, 2, "n = 0 is never a rate");
  assert.doesNotMatch(empty, /50%/);
  const zero = await p.getByRole("row").filter({ hasText: "zero check" }).innerText();
  assert.equal(zero.match(/0%/g)?.length, 2);
  const dev = await p.getByRole("row").filter({ hasText: "Development set" }).innerText();
  assert.match(dev, /Not evaluated/);
  assert.match(dev, /0 of 8 \(0%\)/);
  assert.equal(await p.locator(".spec__row").filter({ hasText: /^Provider failure rate/ }).locator("dd").innerText(), "Not provided");
  await p.screenshot({ path: `${OUT}/missing-desktop.png`, fullPage: true });
  await ctx.close();
  console.log("ok  missing vs zero");
}

// No per-split numbers on an older run.
{
  const { p, ctx } = await open(withRun({ by_split: null }));
  const main = await text(p);
  assert.match(main, /no separate numbers per split/);
  assert.match(main, /stored before per-split numbers/);
  await ctx.close();
  console.log("ok  older run");
}

// A held-out headline, if the API starts sending one.
{
  const { p, ctx } = await open(withRun({ headline: { split: "heldout", n: 25, catch_rate: { numerator: 18, denominator: 18, value: 1 }, false_positive_rate: { numerator: 1, denominator: 7, value: 1 / 7 } } }));
  const metrics = await p.locator(".add-metric").allInnerTexts();
  assert.match(metrics[0], /18 of 18/);
  assert.match(metrics[0], /Held-out/);
  assert.doesNotMatch(await text(p), /combine every split/);
  await ctx.close();
  console.log("ok  held-out headline");
}

// Counts behind the combined rates and each check, when the API sends them.
{
  const ratio = { numerator: 37, denominator: 40, value: 0.925 };
  const { p, ctx } = await open(
    withRun({
      catch_rate_ratio: ratio,
      false_positive_rate_ratio: { numerator: 0, denominator: 40, value: 0 },
      per_check: [{ check: "numeric", catch_rate: 0.925, false_positive_rate: 0, n: 80, catch_rate_ratio: ratio, false_positive_rate_ratio: { numerator: 0, denominator: 40, value: 0 } }],
    }),
  );
  const metrics = await p.locator(".add-metric").allInnerTexts();
  assert.match(metrics[0], /37 of 40 \(92\.5%\)/);
  assert.match(metrics[0], /All splits combined/);
  assert.match(metrics[1], /0 of 40 \(0%\)/);
  assert.match(await p.getByRole("row").filter({ hasText: "numeric" }).innerText(), /37 of 40/);
  assert.doesNotMatch(await text(p), /Counts not supplied/);
  await ctx.close();
  console.log("ok  counts from the API");
}

// A wrong shape is an error, never shown as data.
{
  const { p, ctx } = await open(withRun({ catch_rate: "high" }));
  const main = await text(p);
  assert.match(main, /Something went wrong/i);
  assert.equal(await p.locator(".add-metric").count(), 0);
  await ctx.close();
  console.log("ok  malformed response rejected");
}

// Scripted answers are called out; opening the page never starts a run.
{
  const { p, ctx, posted } = await open(withRun({ provider_mode: "scripted" }));
  assert.match(await text(p), /not a real model/i);
  assert.equal(posted(), 0);
  await ctx.close();
  console.log("ok  scripted run labelled; no run started");
}

// Phone width.
{
  const { p, ctx } = await open(withRun({}), { width: 390, height: 844 });
  assert.equal(await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
  await p.screenshot({ path: `${OUT}/run-mobile.png`, fullPage: true });
  await ctx.close();
  console.log("ok  phone width");
}
await b.close();
console.log("scorecard states: all passed");
