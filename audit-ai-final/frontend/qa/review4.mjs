// Sources rows, seal journey (start / middle / landed), process step scroll length.
import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const errs = [];
p.on("pageerror", (e) => errs.push(e.message));
await p.goto("http://localhost:3000/", { waitUntil: "networkidle" });
await p.evaluate(() => document.fonts.ready);
const go = async (js, name, wait = 1600) => {
  await p.evaluate(js);
  await p.waitForTimeout(wait);
  await p.screenshot({ path: `qa/out/${name}.png` });
};
await go(() => scrollTo(0, document.querySelector(".sources__list").getBoundingClientRect().top + scrollY - 100), "r4-sources");
// seal: trigger runs from hole centre at 60% viewport to target centre at 60% viewport
const pos = await p.evaluate(() => {
  const y = (s) => { const r = document.querySelector(s).getBoundingClientRect(); return r.top + r.height / 2 + scrollY; };
  return { a: y("[data-seal-source]") - innerHeight * 0.6, b: y("[data-seal-target]") - innerHeight * 0.6 };
});
for (const [n, f] of [["start", 0.02], ["mid", 0.5], ["land", 1.02]]) {
  await go((y) => scrollTo(0, y), `r4-seal-${n}`, 2200);
  await p.evaluate((y) => scrollTo(0, y), pos.a + (pos.b - pos.a) * f);
  await p.waitForTimeout(2200);
  await p.screenshot({ path: `qa/out/r4-seal-${n}.png` });
}
const proc = await p.evaluate(() => { const s = document.querySelector("#process"); return { h: s.offsetHeight, vh: innerHeight }; });
console.log("process extra scroll per step (px):", Math.round((proc.h - proc.vh) / 3), "errors:", errs);
await b.close();
