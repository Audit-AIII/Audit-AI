// Reads computed styles from the style reference site to calibrate [R]/[I] tokens.
// Usage: node qa/probe.mjs  → writes ../design/probe.json
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const URL = "https://relevovinco.com";
const SELECTORS = [
  ".m-btn", ".m-link-2", ".m-field__input", ".nav__bar", ".nav", ".hero", ".hero__word", ".hero__channel",
  ".hero__wash", ".hero__light", ".finishes__swatch", ".work__sleeve", ".work__rim", ".process__step",
  ".materials__disc", ".faq__summary", "body",
];
const PROPS = [
  "box-shadow", "text-shadow", "transform", "transition", "animation", "background-image", "background-size",
  "background-position", "background-color", "color", "font-family", "font-size", "line-height", "letter-spacing",
  "padding", "border-radius", "width", "height", "mix-blend-mode", "opacity", "filter", "position", "inset", "z-index",
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1182, height: 937 } });
await page.goto(URL, { waitUntil: "networkidle", timeout: 60000 });
await page.waitForTimeout(1500);

const read = (sel, pseudo) =>
  page.evaluate(({ sel, PROPS, pseudo }) => {
    const els = [...document.querySelectorAll(sel)].slice(0, 4);
    return els.map((el) => {
      const cs = getComputedStyle(el, pseudo);
      const r = el.getBoundingClientRect();
      const out = { class: el.className?.toString?.() ?? "", text: (el.textContent || "").trim().slice(0, 40),
        rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] };
      for (const p of PROPS) out[p] = cs.getPropertyValue(p);
      return out;
    });
  }, { sel, PROPS, pseudo });

const result = { url: URL, viewport: "1182x937", at: new Date().toISOString(), elements: {}, hover: {}, keyframes: {}, rootVars: {} };
for (const s of SELECTORS) {
  result.elements[s] = await read(s, null);
  if ([".m-btn", ".m-link-2", ".hero__word"].includes(s)) {
    result.elements[s + "::before"] = await read(s, "::before");
    result.elements[s + "::after"] = await read(s, "::after");
  }
}

for (const s of [".m-btn", ".m-link-2"]) {
  const el = await page.$(s);
  if (!el) continue;
  await el.hover();
  await page.waitForTimeout(600);
  result.hover[s] = await read(s, null);
}

// keyframes + :root custom properties from same-origin stylesheets
Object.assign(result, await page.evaluate(() => {
  const keyframes = {}, rootVars = {}, rules = [];
  for (const sheet of document.styleSheets) {
    let list; try { list = sheet.cssRules; } catch { continue; }
    const walk = (rs) => { for (const r of rs) {
      if (r.type === 7) keyframes[r.name] = r.cssText;
      else if (r.cssRules) walk(r.cssRules);
      if (r.selectorText && /hero|m-btn|m-link|nav__bar|paper|grain|body|html/.test(r.selectorText)) rules.push(r.cssText.slice(0, 900));
    } };
    walk(list);
  }
  const cs = getComputedStyle(document.documentElement);
  for (const p of cs) if (p.startsWith("--")) rootVars[p] = cs.getPropertyValue(p).trim();
  return { keyframes, rootVars, rules };
}));

await page.screenshot({ path: "qa/out/ref-hero-live.png" });
writeFileSync("../design/probe.json", JSON.stringify(result, null, 2));
await browser.close();
console.log("ok", Object.keys(result.elements).map((k) => `${k}:${result.elements[k].length}`).join(" "));
