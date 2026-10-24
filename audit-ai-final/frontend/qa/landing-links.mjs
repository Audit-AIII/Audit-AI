// Landing page: every Process step sits with the same margin as step 1 (no drift while scrolling),
// every in-page link lands just under the fixed header (FAQ targets open), page links answer, and
// the footer names the team. node qa/landing-links.mjs (frontend on :3000)
import { chromium } from "playwright";
import assert from "node:assert/strict";

const WEB = "http://localhost:3000";
const b = await chromium.launch();
const errors = [];

// 1) Process: equal margin all round on every step, at two desktop widths
for (const [w, h] of [[1440, 900], [1182, 937]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(`${WEB}/`, { waitUntil: "networkidle" }); await p.waitForTimeout(1200);
  const { top, height } = await p.evaluate(() => { const s = document.getElementById("process"); return { top: s.getBoundingClientRect().top + scrollY, height: s.offsetHeight }; });
  const gaps = [];
  for (let i = 0; i < 4; i++) {
    await p.evaluate((y) => window.scrollTo(0, y), top + (height - h) * ((i + 0.5) / 4)); await p.waitForTimeout(2600);
    gaps.push(await p.evaluate((k) => { const ch = document.querySelector(".process__channel").getBoundingClientRect(); const c = document.querySelectorAll(".process__step")[k].getBoundingClientRect(); return [c.left - ch.left, ch.right - c.right, c.top - ch.top, ch.bottom - c.bottom].map(Math.round); }, i));
  }
  for (const g of gaps) for (const v of g) assert.ok(Math.abs(v - gaps[0][0]) <= 1, `${w}px: step margins ${JSON.stringify(gaps)}`);
  console.log(`ok  ${w}px: all four steps sit ${gaps[0][0]}px from the frame on every side`);
  await p.close();
}

// 2) In-page links land under the header; FAQ answers open; page links answer
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
p.on("pageerror", (e) => errors.push(e.message));
await p.goto(`${WEB}/`, { waitUntil: "networkidle" });
const links = await p.evaluate(() => [...document.querySelectorAll("a[href]:not(.skip-link)")].map((a, i) => ({ i, href: a.getAttribute("href"), text: a.textContent.trim().replace(/\s+/g, " ") })));
for (const l of links) {
  if (!l.href.includes("#")) {
    const res = await p.request.get(new URL(l.href, WEB).toString());
    assert.equal(res.status(), 200, l.href);
    continue;
  }
  await p.goto(`${WEB}/`, { waitUntil: "networkidle" }); await p.waitForTimeout(600);
  // Clicked from a fresh page without jumping there first: a native jump bypasses Lenis, whose
  // remembered position would then be stale (a visitor scrolling normally never hits that).
  const a = p.locator("a[href]:not(.skip-link)").nth(l.i);
  await a.evaluate((el) => el.click()); await p.waitForTimeout(3200);
  const r = await p.evaluate((href) => {
    const el = document.getElementById(href.split("#")[1]);
    const atEnd = Math.ceil(scrollY + innerHeight) >= document.documentElement.scrollHeight - 2;
    return el ? { top: Math.round(el.getBoundingClientRect().top), details: el.tagName === "DETAILS", open: el.tagName === "DETAILS" && el.open, atEnd } : null;
  }, l.href);
  assert.ok(r, `${l.text}: target ${l.href} exists`);
  // under the 68px header and in view; a target near the page end can't scroll higher than the end
  assert.ok((r.top >= 0 && r.top <= 100) || (r.atEnd && r.top < 900), `${l.text} ${l.href}: landed at ${r.top}px`);
  if (r.details) assert.ok(r.open, `${l.text}: FAQ answer opened`);
}
console.log(`ok  ${links.length} links: in-page ones land under the header (FAQ answers open), page links answer 200`);

// 3) Footer: hackathon name, team, Trust links go to real screens
const footer = await p.locator(".footer").innerText();
assert.match(footer, /TechCircuit hackathon/); assert.doesNotMatch(footer, /Inkloom AI hackathon/);
for (const n of ["Chahit Doshi", "Krish Dodiya", "Darsh Shah", "Daneeka Roy"]) assert.ok(footer.includes(n), n);
assert.deepEqual(await p.locator(".footer nav[aria-label=Trust] a").evaluateAll((as) => as.map((a) => a.getAttribute("href"))), ["#data-passport", "#faq-data", "#faq-legal"]);
console.log("ok  footer: TechCircuit hackathon, four team members, Trust links -> Data Passport / Where does my data go / Is this legal advice");
assert.deepEqual(errors, []); console.log("ok  no page errors"); await b.close();
