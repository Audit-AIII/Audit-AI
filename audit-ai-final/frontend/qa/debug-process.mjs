import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
p.on("pageerror", (e) => console.log("err", e.message));
await p.goto("http://localhost:3100/", { waitUntil: "networkidle" }); await p.waitForTimeout(1500);
const info = () => p.evaluate(() => { const s = document.querySelector("#process"), t = document.querySelector(".process__track"), c = document.querySelector(".process__channel");
  return { y: Math.round(scrollY), top: Math.round(s.getBoundingClientRect().top + scrollY), h: s.offsetHeight, attr: s.hasAttribute("data-track"), dist: s.style.getPropertyValue("--process-distance"), tw: t.scrollWidth, cw: c.clientWidth, tf: getComputedStyle(t).transform }; });
console.log(await info());
const i0 = await info();
for (const f of [0.33, 0.66, 1]) { await p.mouse.wheel(0, 0); await p.evaluate((y) => scrollTo(0, y), i0.top + (i0.h - 937) * f); await p.waitForTimeout(1500); console.log(f, await info()); }
await b.close();
