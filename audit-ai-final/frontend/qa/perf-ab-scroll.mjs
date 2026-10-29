// A/B of the landing-page scroll on one build: "svg" disables GrainBake (no createImageBitmap, so it
// bails out and the SVG grain tokens stay), "baked" is the shipped behaviour. N runs each, medians.
//   node qa/perf-ab-scroll.mjs [runs=5]
import { chromium } from "playwright";

const WEB = process.env.WEB ?? "http://localhost:3000";
const RUNS = Number(process.argv[2] ?? 5);
const PROFILES = {
  mobile: { ctx: { viewport: { width: 412, height: 823 }, deviceScaleFactor: 1.75, isMobile: true, hasTouch: true }, cpu: 4 },
  desktop: { ctx: { viewport: { width: 1350, height: 940 } }, cpu: 1 },
};
const med = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];

async function once(b, profile, variant) {
  const { ctx: opts, cpu } = PROFILES[profile];
  const ctx = await b.newContext(opts);
  if (variant === "svg") await ctx.addInitScript(() => { delete window.createImageBitmap; });
  await ctx.addInitScript(() => {
    window.__lt = [];
    new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__lt.push([e.startTime, e.duration]))).observe({ type: "longtask" });
  });
  const p = await ctx.newPage();
  if (cpu > 1) await (await ctx.newCDPSession(p)).send("Emulation.setCPUThrottlingRate", { rate: cpu });
  await p.goto(WEB + "/", { waitUntil: "load" });
  await p.waitForTimeout(4000);
  await p.mouse.move(200, 400);
  await p.evaluate(() => {
    window.__t0 = performance.now();
    window.__f = [];
    let last = performance.now();
    const tick = (t) => { window.__f.push(t - last); last = t; window.__raf = requestAnimationFrame(tick); };
    window.__raf = requestAnimationFrame(tick);
  });
  await b.startTracing(p, { categories: ["devtools.timeline", "disabled-by-default-devtools.timeline"] });
  for (let i = 0; i < 60; i++) { await p.mouse.wheel(0, 240); await p.waitForTimeout(50); }
  await p.waitForTimeout(1000);
  const ev = JSON.parse((await b.stopTracing()).toString()).traceEvents;
  const raster = Math.round(ev.filter((e) => e.name === "RasterTask" && e.ph === "X").reduce((s, e) => s + (e.dur || 0), 0) / 1000);
  const r = await p.evaluate(() => {
    cancelAnimationFrame(window.__raf);
    const f = window.__f.slice(2);
    const lt = window.__lt.filter(([s]) => s >= window.__t0);
    return { dropped: f.reduce((n, d) => n + Math.max(0, Math.round(d / 16.67) - 1), 0), worst: Math.round(Math.max(...f)), longTasks: lt.length, longest: Math.round(Math.max(0, ...lt.map(([, d]) => d))) };
  });
  await ctx.close();
  return { ...r, raster };
}

const b = await chromium.launch();
for (const profile of Object.keys(PROFILES)) {
  for (const variant of ["svg", "baked"]) {
    const runs = [];
    for (let i = 0; i < RUNS; i++) runs.push(await once(b, profile, variant));
    const m = Object.fromEntries(Object.keys(runs[0]).map((k) => [k, med(runs.map((r) => r[k]))]));
    console.log(profile.padEnd(8), variant.padEnd(6), "median", JSON.stringify(m), "| longTasks per run", runs.map((r) => r.longTasks).join(","), "| longest per run", runs.map((r) => r.longest).join(","));
  }
}
await b.close();
