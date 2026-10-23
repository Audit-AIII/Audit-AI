// Measures width ratios web font vs Arial to set size-adjust on the metric fallbacks in styles/base.css.
import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage();
await p.goto("http://localhost:3000/", { waitUntil: "networkidle" }); await p.evaluate(() => document.fonts.ready);
console.log(await p.evaluate(() => {
  const s = "Audit AI reviews every draft against your approved guidelines CHECK FIRST PUBLISH SURE 0123";
  const c = document.createElement("canvas").getContext("2d"); const w = (f) => { c.font = f; return c.measureText(s).width; };
  return { gabarito: (w("700 100px 'Gabarito Variable'") / w("700 100px Arial")).toFixed(3), instrument: (w("400 100px 'Instrument Sans Variable'") / w("400 100px Arial")).toFixed(3) };
}));
await b.close();
