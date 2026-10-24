// Load + smoothness probe (run against `next build && next start`, CPU throttled 4x like a mid
// laptop/phone). Per page: FCP, LCP, JS / total transfer, blocking time (long tasks over 50ms), and
// frame times while scrolling the whole page (avg fps, % frames over 50ms = visible stutter).
// AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/perf.mjs [label]
import { chromium } from "playwright";

const WEB = process.env.WEB ?? "http://localhost:3000";
const label = process.argv[2] ?? "run";
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
const p = await ctx.newPage();
const cdp = await ctx.newCDPSession(p);

await p.addInitScript(() => {
  window.__lt = 0;
  window.__lcp = 0;
  new PerformanceObserver((l) => l.getEntries().forEach((e) => (window.__lt += Math.max(0, e.duration - 50)))).observe({ type: "longtask", buffered: true });
  new PerformanceObserver((l) => l.getEntries().forEach((e) => (window.__lcp = e.startTime))).observe({ type: "largest-contentful-paint", buffered: true });
});

async function measure(path, { scroll = true } = {}) {
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await p.goto(WEB + path, { waitUntil: "load" });
  await p.waitForTimeout(2500);
  const load = await p.evaluate(() => {
    const fcp = performance.getEntriesByName("first-contentful-paint")[0]?.startTime ?? 0;
    const res = performance.getEntriesByType("resource");
    const kb = (f) => Math.round(res.filter(f).reduce((n, r) => n + (r.transferSize || 0), 0) / 1024);
    return { fcp: Math.round(fcp), lcp: Math.round(window.__lcp), jsKB: kb((r) => r.initiatorType === "script"), allKB: kb(() => true), blockingMs: Math.round(window.__lt) };
  });
  let frames = null;
  if (scroll) {
    await p.evaluate(() => {
      window.__f = [];
      let last = performance.now();
      const tick = (t) => { window.__f.push(t - last); last = t; if (window.__f.length < 100000) window.__raf = requestAnimationFrame(tick); };
      window.__raf = requestAnimationFrame(tick);
    });
    const height = await p.evaluate(() => document.documentElement.scrollHeight);
    const steps = Math.min(120, Math.ceil(height / 160));
    await p.mouse.move(700, 450);
    for (let i = 0; i < steps; i++) { await p.mouse.wheel(0, 160); await p.waitForTimeout(60); }
    await p.waitForTimeout(800);
    frames = await p.evaluate(() => {
      cancelAnimationFrame(window.__raf);
      const f = window.__f.slice(2);
      const avg = f.reduce((a, b) => a + b, 0) / f.length;
      return { fps: Math.round(1000 / avg), jankPct: +((100 * f.filter((d) => d > 50).length) / f.length).toFixed(1), worstMs: Math.round(Math.max(...f)) };
    });
  }
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
  const row = { path, ...load, ...(frames ?? {}) };
  console.log(`${label}\t${JSON.stringify(row)}`);
  return row;
}

await measure("/");
await measure("/login", { scroll: false });
if (process.env.AUDIT_PASSWORD) {
  await p.goto(`${WEB}/login?next=%2Fapp%2Fqueue`, { waitUntil: "networkidle" });
  await p.fill("#a-email", process.env.AUDIT_EMAIL ?? "ben@seed.inkloom.demo");
  await p.fill("#a-password", process.env.AUDIT_PASSWORD);
  await p.click("button[type=submit]");
  await p.waitForURL("**/app/queue");
  const t = JSON.parse(await p.evaluate(() => localStorage.getItem("audit-ai.session"))).token;
  const rid = (await (await fetch("http://localhost:8000/api/reviews?limit=1", { headers: { Authorization: `Bearer ${t}` } })).json())[0]?.id;
  await measure("/app/insights");
  await measure("/app/queue");
  if (rid) await measure(`/app/review?id=${rid}`);
  await measure("/app/sources");
}
await b.close();
