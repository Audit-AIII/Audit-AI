import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("https://relevovinco.com", { waitUntil: "networkidle" }); await p.waitForTimeout(800);
// force reveals
await p.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 600) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); } });
await p.waitForTimeout(800);
const r = await p.evaluate(() => {
  const cs0 = getComputedStyle(document.documentElement); const vars = {};
  for (const k of ["--shadow-6","--shadow-7","--shadow-10","--shadow-11","--shadow-14","--shadow-15","--shadow-16","--shadow-17"]) vars[k] = cs0.getPropertyValue(k).trim();
  const pick = (s) => [...document.querySelectorAll(s)].slice(0, 2).map(e => { const c = getComputedStyle(e); return { s, cls: e.className.toString(), txt: e.textContent.trim().slice(0, 30), fs: c.fontSize, lh: c.lineHeight, ls: c.letterSpacing, fw: c.fontWeight, ff: c.fontFamily.slice(0,12), col: c.color, ts: c.textShadow, tt: c.textTransform, mw: c.maxWidth }; });
  const out = [];
  for (const s of ["h2", "h3", ".craft__line", ".craft__roller", ".craft__note p", ".nav__brand", "#studio h2", "#studio blockquote, #studio .studio__quote", "#footer *", ".finishes__head p, #finishes p", ".m-caption, dt", ".faq__summary", "label", "#contact h2", ".kit__price, #kit [class*=price]", "#process [class*=num], #process [class*=step] span"]) out.push(...pick(s));
  const foot = document.querySelector("#footer"); const fr = foot.getBoundingClientRect();
  return { vars, out, footer: foot.innerText.slice(0, 600), footerH: fr.height, footerBg: getComputedStyle(foot).backgroundColor };
});
console.log(JSON.stringify(r, null, 1));
await p.evaluate(() => document.querySelector("#footer").scrollIntoView()); await p.waitForTimeout(800);
await p.screenshot({ path: "qa/out/ref-footer.png" });
await p.evaluate(() => document.querySelector("#process").scrollIntoView()); await p.waitForTimeout(1200);
await p.screenshot({ path: "qa/out/ref-process.png" });
await p.evaluate(() => document.querySelector("#faq").scrollIntoView()); await p.waitForTimeout(800);
await p.screenshot({ path: "qa/out/ref-faq.png" });
await p.evaluate(() => document.querySelector("#contact").scrollIntoView()); await p.waitForTimeout(800);
await p.screenshot({ path: "qa/out/ref-contact.png" });
await p.evaluate(() => document.querySelector("#kit").scrollIntoView()); await p.waitForTimeout(800);
await p.screenshot({ path: "qa/out/ref-kit.png" });
await b.close();
