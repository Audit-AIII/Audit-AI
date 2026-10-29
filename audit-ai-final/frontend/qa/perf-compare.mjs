// Before/after on two running production builds, runs alternated so both see the same machine load.
//   BEFORE=http://localhost:3001 AFTER=http://localhost:3000 node qa/perf-compare.mjs [runs=5]
// Per profile: scripted scroll of `/` (frames, long tasks, raster/paint) and 3 s of idle on `/`.
// Prints medians and writes qa/out/perf-compare.json.
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const SITES = { before: process.env.BEFORE ?? "http://localhost:3001", after: process.env.AFTER ?? "http://localhost:3000" };
const RUNS = Number(process.argv[2] ?? 5);
const PROFILES = {
  mobile: { ctx: { viewport: { width: 412, height: 823 }, deviceScaleFactor: 1.75, isMobile: true, hasTouch: true }, cpu: 4 },
  desktop: { ctx: { viewport: { width: 1350, height: 940 } }, cpu: 1 },
};
const CATS = ["devtools.timeline", "disabled-by-default-devtools.timeline"];
const med = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];
const sum = (ev, n) => Math.round(ev.filter((e) => e.name === n && e.ph === "X").reduce((s, e) => s + (e.dur || 0), 0) / 1000);

async function page(b, profile) {
  const { ctx: opts, cpu } = PROFILES[profile];
  const ctx = await b.newContext(opts);
  await ctx.addInitScript(() => {
    window.__lt = [];
    new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__lt.push([e.startTime, e.duration]))).observe({ type: "longtask" });
  });
  const p = await ctx.newPage();
  if (cpu > 1) await (await ctx.newCDPSession(p)).send("Emulation.setCPUThrottlingRate", { rate: cpu });
  return { ctx, p };
}

async function scroll(b, profile, web) {
  const { ctx, p } = await page(b, profile);
  await p.goto(web + "/", { waitUntil: "load" });
  await p.waitForTimeout(4000);
  await p.mouse.move(200, 400);
  await p.evaluate(() => {
    window.__t0 = performance.now();
    window.__f = [];
    let last = performance.now();
    const tick = (t) => { window.__f.push(t - last); last = t; window.__raf = requestAnimationFrame(tick); };
    window.__raf = requestAnimationFrame(tick);
  });
  await b.startTracing(p, { categories: CATS });
  const h = await p.evaluate(() => document.documentElement.scrollHeight);
  for (let i = 0; i < Math.ceil(h / 240) + 10; i++) { await p.mouse.wheel(0, 240); await p.waitForTimeout(50); }
  await p.waitForTimeout(1000);
  const ev = JSON.parse((await b.stopTracing()).toString()).traceEvents;
  const r = await p.evaluate(() => {
    cancelAnimationFrame(window.__raf);
    const f = window.__f.slice(2);
    const lt = window.__lt.filter(([s]) => s >= window.__t0);
    return {
      fps: Math.round((1000 * f.length) / f.reduce((a, c) => a + c, 0)),
      dropped: f.reduce((n, d) => n + Math.max(0, Math.round(d / 16.67) - 1), 0),
      worstMs: Math.round(Math.max(...f)),
      longTasks: lt.length,
      longestMs: Math.round(Math.max(0, ...lt.map(([, d]) => d))),
    };
  });
  await ctx.close();
  return { ...r, rasterMs: sum(ev, "RasterTask"), paintMs: sum(ev, "Paint"), paints: ev.filter((e) => e.name === "Paint").length };
}

async function idle(b, profile, web) {
  const { ctx, p } = await page(b, profile);
  await p.goto(web + "/", { waitUntil: "load" });
  await p.waitForTimeout(4000);
  await b.startTracing(p, { categories: CATS });
  await p.waitForTimeout(3000);
  const ev = JSON.parse((await b.stopTracing()).toString()).traceEvents;
  await ctx.close();
  return { paints: ev.filter((e) => e.name === "Paint").length, paintMs: sum(ev, "Paint"), rasterMs: sum(ev, "RasterTask") };
}

const b = await chromium.launch();
const out = {};
for (const profile of Object.keys(PROFILES)) {
  for (const [test, fn] of [["scroll", scroll], ["idle", idle]]) {
    const runs = { before: [], after: [] };
    for (let i = 0; i < RUNS; i++) for (const site of ["before", "after"]) runs[site].push(await fn(b, profile, SITES[site]));
    for (const site of ["before", "after"]) {
      const m = Object.fromEntries(Object.keys(runs[site][0]).map((k) => [k, med(runs[site].map((r) => r[k]))]));
      out[`${profile} ${test} ${site}`] = { median: m, runs: runs[site] };
      console.log(`${profile.padEnd(8)}${test.padEnd(7)}${site.padEnd(7)}`, JSON.stringify(m));
    }
  }
}
await b.close();
mkdirSync(new URL("./out/", import.meta.url), { recursive: true });
writeFileSync(new URL("./out/perf-compare.json", import.meta.url), JSON.stringify(out, null, 2));
