// Sanity checks: no horizontal overflow (desktop + mobile), one H1, reduced-motion shows all content.
import { chromium } from "playwright";
const b = await chromium.launch();
for (const [w, h, rm] of [[1182, 937, "no-preference"], [390, 844, "no-preference"], [390, 844, "reduce"]]) {
  const p = await b.newPage({ viewport: { width: w, height: h }, reducedMotion: rm });
  const errs = []; p.on("pageerror", (e) => errs.push(e.message));
  await p.goto("http://localhost:3000/", { waitUntil: "networkidle" });
  await p.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) { scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)); } });
  await p.waitForTimeout(800);
  const r = await p.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - innerWidth,
    wide: [...document.querySelectorAll("body *")].filter((e) => { const r = e.getBoundingClientRect(); return r.right > innerWidth + 1 && !e.closest(".process__channel,.hero__flap,.statement__flap"); }).slice(0, 5).map((e) => e.className.toString().slice(0, 40)),
    h1: document.querySelectorAll("h1").length,
    hidden: [...document.querySelectorAll("[data-r]")].filter((e) => getComputedStyle(e).opacity === "0").length,
    height: document.body.scrollHeight,
  }));
  console.log(`${w}x${h} ${rm}`, JSON.stringify(r), errs.length ? errs : "");
  await p.close();
}
await b.close();
