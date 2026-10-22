import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("http://localhost:3100/", { waitUntil: "networkidle" }); await p.evaluate(() => document.fonts.ready);
for (const [i, frac] of [[0, 0.15], [1, 0.62]].entries ? [[0, 0.15], [1, 0.62]] : []) {
  await p.evaluate((f) => { const g = document.querySelector(".checks__grid"); scrollTo(0, g.getBoundingClientRect().top + scrollY + g.offsetHeight * f - 300); }, frac);
  await p.waitForTimeout(2200);
  await p.screenshot({ path: `qa/out/cards-${i}.png` });
}
await b.close();
