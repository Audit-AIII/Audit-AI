// Load, scroll and transition probe for PERF_BASELINE.md / PERF_RESULT.md. Run against a production
// build (`npm run build && npm start`), never `next dev`.
//   node qa/perf-r3.mjs <label> [runs=3]          WEB=https://… to measure a deployed site
// Writes qa/out/perf-<label>.json and prints a summary.
//
// Profiles: "mobile" = 412x823 @1.75x, CPU 4x slower, 150ms RTT / 1.6 Mbps (Lighthouse's mobile
// defaults); "desktop" = 1350x940, no throttling. Load metrics are the median of `runs` cold loads.
// /app pages get a stored session and no backend (connection refused), which is what a deployed
// frontend without a reachable API sees. Headless Chromium rasterises in software, so paint and
// raster times are higher than on a GPU; compare runs with each other, not with a real phone.
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const WEB = process.env.WEB ?? "http://localhost:3000";
const label = process.argv[2] ?? "run";
const RUNS = Number(process.argv[3] ?? 3);

const PROFILES = {
  mobile: { viewport: { width: 412, height: 823 }, deviceScaleFactor: 1.75, isMobile: true, hasTouch: true, cpu: 4, net: { latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 } },
  desktop: { viewport: { width: 1350, height: 940 }, deviceScaleFactor: 1, isMobile: false, hasTouch: false, cpu: 1, net: null },
};
const ROUTES = ["/", "/login", "/app/sources", "/app/review"];

const SESSION = JSON.stringify({ email: "perf@example.test", token: "perf-token", userId: "u1", organisation: { id: "o1", name: "Perf", slug: "perf" }, role: "admin" });

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
};

const observers = () => {
  window.__perf = { lcp: 0, cls: 0, longtasks: [] };
  new PerformanceObserver((l) => l.getEntries().forEach((e) => (window.__perf.lcp = e.startTime))).observe({ type: "largest-contentful-paint", buffered: true });
  new PerformanceObserver((l) => l.getEntries().forEach((e) => { if (!e.hadRecentInput) window.__perf.cls += e.value; })).observe({ type: "layout-shift", buffered: true });
  new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__perf.longtasks.push([e.startTime, e.duration]))).observe({ type: "longtask", buffered: true });
};

async function newPage(browser, profile, { signedIn = false } = {}) {
  const { cpu, net, ...ctxOpts } = PROFILES[profile];
  const ctx = await browser.newContext(ctxOpts);
  if (signedIn) await ctx.addInitScript((s) => localStorage.setItem("audit-ai.session", s), SESSION);
  await ctx.addInitScript(observers);
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  if (net) await cdp.send("Network.emulateNetworkConditions", { offline: false, ...net });
  if (cpu > 1) await cdp.send("Emulation.setCPUThrottlingRate", { rate: cpu });
  return { ctx, page, cdp };
}

async function load(browser, profile, path) {
  const { ctx, page } = await newPage(browser, profile, { signedIn: path.startsWith("/app") });
  await page.goto(WEB + path, { waitUntil: "load", timeout: 90000 });
  await page.waitForTimeout(5000);
  const m = await page.evaluate(() => {
    const fcp = performance.getEntriesByName("first-contentful-paint")[0]?.startTime ?? 0;
    const res = performance.getEntriesByType("resource");
    const kb = (f) => Math.round((res.filter(f).reduce((n, r) => n + (r.transferSize || 0), 0) / 1024) * 10) / 10;
    const nav = performance.getEntriesByType("navigation")[0];
    const tbt = window.__perf.longtasks.filter(([s]) => s >= fcp).reduce((n, [, d]) => n + Math.max(0, d - 50), 0);
    return {
      fcp: Math.round(fcp),
      lcp: Math.round(window.__perf.lcp),
      cls: Math.round(window.__perf.cls * 1000) / 1000,
      tbt: Math.round(tbt),
      jsKB: kb((r) => /\.js(\?|$)/.test(r.name)),
      cssKB: kb((r) => /\.css(\?|$)/.test(r.name)),
      fontKB: kb((r) => /\.woff2?(\?|$)/.test(r.name)),
      docKB: Math.round(((nav?.transferSize ?? 0) / 1024) * 10) / 10,
      requests: res.length,
    };
  });
  await ctx.close();
  return m;
}

const TRACE_CATS = ["devtools.timeline", "disabled-by-default-devtools.timeline", "disabled-by-default-devtools.timeline.frame"];
const PAINT_EVENTS = ["Paint", "RasterTask", "Layout", "UpdateLayoutTree", "PrePaint", "Layerize", "CompositeLayers", "Decode Image", "FunctionCall", "GPUTask"];

function summariseTrace(buf) {
  const events = JSON.parse(buf.toString()).traceEvents ?? [];
  const sums = Object.fromEntries(PAINT_EVENTS.map((n) => [n, 0]));
  let paints = 0;
  for (const e of events) {
    if (e.ph !== "X" || !(e.name in sums)) continue;
    sums[e.name] += (e.dur ?? 0) / 1000;
    if (e.name === "Paint") paints++;
  }
  return { paintCount: paints, ms: Object.fromEntries(Object.entries(sums).map(([k, v]) => [k, Math.round(v)])) };
}

/** Scripted wheel scroll from top to bottom of `/`, then back to top: frame times, long tasks, paint/raster. */
async function scroll(browser, profile) {
  const { ctx, page } = await newPage(browser, profile);
  await page.goto(WEB + "/", { waitUntil: "load", timeout: 90000 });
  await page.waitForTimeout(4000);
  await page.mouse.move(PROFILES[profile].viewport.width / 2, PROFILES[profile].viewport.height / 2);
  await page.evaluate(() => {
    window.__frames = [];
    window.__scrollStart = performance.now();
    let last = performance.now();
    const tick = (t) => { window.__frames.push(t - last); last = t; window.__raf = requestAnimationFrame(tick); };
    window.__raf = requestAnimationFrame(tick);
  });
  await browser.startTracing(page, { categories: TRACE_CATS });
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  const steps = Math.ceil(height / 240) + 10;
  for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, 240); await page.waitForTimeout(50); }
  await page.waitForTimeout(1200);
  const trace = summariseTrace(await browser.stopTracing());
  const r = await page.evaluate(() => {
    cancelAnimationFrame(window.__raf);
    const f = window.__frames.slice(2);
    const total = f.reduce((a, b) => a + b, 0);
    const lt = window.__perf.longtasks.filter(([s]) => s >= window.__scrollStart);
    return {
      fps: Math.round((1000 * f.length) / total),
      frames: f.length,
      droppedFrames: f.reduce((n, d) => n + Math.max(0, Math.round(d / 16.67) - 1), 0),
      jankPct: Math.round((1000 * f.filter((d) => d > 50).length) / f.length) / 10,
      worstFrameMs: Math.round(Math.max(...f)),
      longTasks: lt.length,
      longestTaskMs: Math.round(Math.max(0, ...lt.map(([, d]) => d))),
      reachedBottom: Math.round(window.scrollY + innerHeight) >= document.documentElement.scrollHeight - 4,
    };
  });
  await ctx.close();
  return { ...r, trace };
}

/** Idle cost of the landing hero: paint/raster over 3s with nothing happening (16s light + sway loops). */
async function idle(browser, profile) {
  const { ctx, page } = await newPage(browser, profile);
  await page.goto(WEB + "/", { waitUntil: "load", timeout: 90000 });
  await page.waitForTimeout(3000);
  await browser.startTracing(page, { categories: TRACE_CATS });
  await page.waitForTimeout(3000);
  const trace = summariseTrace(await browser.stopTracing());
  await ctx.close();
  return trace;
}

/** / -> /login (client navigation) and / -> /app (sand-wave), desktop profile. */
async function navigation(browser) {
  const out = {};
  {
    const { ctx, page } = await newPage(browser, "desktop");
    await page.goto(WEB + "/", { waitUntil: "load" });
    await page.waitForTimeout(2000);
    const t0 = await page.evaluate(() => performance.now());
    await page.locator('header a[href="/login"]').first().click();
    await page.waitForURL("**/login");
    await page.locator("#auth-title").waitFor();
    out.homeToLoginMs = Math.round((await page.evaluate(() => performance.now())) - t0);
    await ctx.close();
  }
  {
    const { ctx, page } = await newPage(browser, "desktop", { signedIn: true });
    await page.goto(WEB + "/", { waitUntil: "load" });
    await page.waitForTimeout(2500);
    const r = await page.evaluate(
      () =>
        new Promise((resolve) => {
          const frames = [];
          let last = performance.now();
          const t0 = last;
          let navAt = null;
          let raf = requestAnimationFrame(function tick(t) {
            frames.push(t - last);
            last = t;
            if (navAt === null && location.pathname.startsWith("/app")) navAt = t - t0;
            const el = document.querySelector(".sandwave");
            const done = navAt !== null && el && getComputedStyle(el).visibility === "hidden";
            if (done || t - t0 > 9000) {
              cancelAnimationFrame(raf);
              const f = frames.slice(1);
              resolve({
                navigationStartsMs: Math.round(navAt ?? -1),
                transitionEndsMs: Math.round(t - t0),
                fps: Math.round((1000 * f.length) / f.reduce((a, b) => a + b, 0)),
                droppedFrames: f.reduce((n, d) => n + Math.max(0, Math.round(d / 16.67) - 1), 0),
                worstFrameMs: Math.round(Math.max(...f)),
              });
            } else raf = requestAnimationFrame(tick);
          });
          window.dispatchEvent(new CustomEvent("sandwave:go", { detail: { href: "/app/sources" } }));
        }),
    );
    out.sandWave = r;
    await ctx.close();
  }
  return out;
}

/** Signed-in /app/sources when the API host accepts the connection but never answers. */
async function hungApi(browser) {
  const { ctx, page } = await newPage(browser, "desktop", { signedIn: true });
  await page.route(/localhost:8000/, () => {}); // never fulfilled
  const t0 = Date.now();
  await page.goto(WEB + "/app/sources", { waitUntil: "load" });
  // Next's route announcer is also role="alert", so wait for the network-error wording itself.
  const shown = await page
    .getByText(/couldn.t reach/i)
    .first()
    .waitFor({ timeout: 40000 })
    .then(() => Date.now() - t0)
    .catch(() => null);
  await ctx.close();
  return { errorShownMs: shown ?? ">40000 (never)" };
}

const browser = await chromium.launch();
const result = { label, web: WEB, runs: RUNS, at: new Date().toISOString(), load: {}, scroll: {}, idle: {}, nav: null, hungApi: null };
for (const profile of Object.keys(PROFILES)) {
  result.load[profile] = {};
  for (const path of ROUTES) {
    const runs = [];
    for (let i = 0; i < RUNS; i++) runs.push(await load(browser, profile, path));
    const med = Object.fromEntries(Object.keys(runs[0]).map((k) => [k, median(runs.map((r) => r[k]))]));
    result.load[profile][path] = med;
    console.log(label, profile, path, JSON.stringify(med));
  }
  result.scroll[profile] = await scroll(browser, profile);
  console.log(label, profile, "scroll /", JSON.stringify(result.scroll[profile]));
  result.idle[profile] = await idle(browser, profile);
  console.log(label, profile, "idle /", JSON.stringify(result.idle[profile]));
}
result.nav = await navigation(browser);
console.log(label, "nav", JSON.stringify(result.nav));
result.hungApi = await hungApi(browser);
console.log(label, "hung API", JSON.stringify(result.hungApi));
await browser.close();

mkdirSync(new URL("./out/", import.meta.url), { recursive: true });
writeFileSync(new URL(`./out/perf-${label}.json`, import.meta.url), JSON.stringify(result, null, 2));
