import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
p.on("console", (m) => console.log("console:", m.text())); p.on("pageerror", (e) => console.log("pageerror:", e.message));
await p.goto("http://localhost:3100/", { waitUntil: "networkidle" }); await p.waitForTimeout(1200);
for (const off of [300, 700]) {
  await p.evaluate((o) => { const g = document.querySelector(".checks__grid"); window.scrollTo(0, g.getBoundingClientRect().top + scrollY - o); }, off);
  await p.waitForTimeout(1800);
  console.log(off, JSON.stringify(await p.evaluate(() => [...document.querySelectorAll(".checks__swatch")].map((c) => { const r = c.getBoundingClientRect(); const cs = getComputedStyle(c); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), cs.transform.slice(0, 40), cs.opacity, cs.visibility]; }))));
  await p.screenshot({ path: `qa/out/dbg-checks-${off}.png` });
}
await b.close();
