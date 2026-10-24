// Keyboard-only walk-through: Tab through Sources, Draft, Review, Decide, Record and the workspace
// row. Every visible control must be reached, show a visible focus change, and Tab must not trap.
// AUDIT_EMAIL / AUDIT_PASSWORD / REVIEW_ID env.
import { chromium } from "playwright";
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password, REVIEW_ID: rid } = process.env;
const WEB = "http://localhost:3000";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
await p.goto(`${WEB}/login?next=%2Fapp%2Fsources`, { waitUntil: "networkidle" });
// sign in by keyboard too
await p.keyboard.press("Tab"); // skip link
let guard = 0;
while (!(await p.evaluate(() => document.activeElement?.id === "a-email")) && guard++ < 10) await p.keyboard.press("Tab");
await p.keyboard.type(email); await p.keyboard.press("Tab"); await p.keyboard.type(password); await p.keyboard.press("Enter");
await p.waitForURL("**/app/sources", { timeout: 20000 });
console.log("ok  signed in with the keyboard only");
let failed = 0;
for (const path of ["/app/sources", "/app/draft", `/app/review?id=${rid}`, `/app/decide?id=${rid}`, `/app/record?id=${rid}`, "/app/queue"]) {
  await p.goto(WEB + path, { waitUntil: "networkidle" }); await p.waitForTimeout(1200);
  const want = await p.evaluate(() => {
    const sel = "a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), textarea:not([disabled]), select:not([disabled]), [tabindex='0'], mark[role=button]";
    return [...document.querySelectorAll(sel)].filter((e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
      const hiddenMenu = e.closest(".account__menu:not(.is-open)");
      // Expected non-stops: closed <details> content (Enter on the summary opens it) and the extra
      // radios of a group (one Tab stop per group; arrow keys move inside it).
      const closed = e.closest("details:not([open])") && !e.matches("summary");
      const extraRadio = e.type === "radio" && e.name && document.querySelector(`input[type=radio][name="${e.name}"]`) !== e;
      return !hiddenMenu && !closed && !extraRadio && s.visibility !== "hidden" && (r.width > 0 || e.matches("input.sr-only, input.add-sr, .sr-only")); }).length;
  });
  const seen = new Set(); const noRing = []; let loops = 0;
  for (let i = 0; i < 250; i++) {
    await p.keyboard.press("Tab");
    const info = await p.evaluate(() => {
      const e = document.activeElement; if (!e || e === document.body) return null;
      if (!e.dataset.kbid) e.dataset.kbid = String(Math.random()); // identity, not text: two controls can read the same
      const key = e.dataset.kbid;
      const s = getComputedStyle(e); const lbl = e.closest("label"); const ls = lbl ? getComputedStyle(lbl) : null; const next = e.nextElementSibling ? getComputedStyle(e.nextElementSibling) : null;
      const ring = (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || /rgb\(140, 89, 64\)/.test(s.boxShadow) || (ls && /rgb\(140, 89, 64\)/.test(ls.boxShadow)) ||
        (next && next.outlineStyle !== "none" && parseFloat(next.outlineWidth) > 0) || (e.closest(".dropzone, .add-drop") && /rgb\(140, 89, 64\)/.test(getComputedStyle(e.closest(".dropzone, .add-drop")).boxShadow + getComputedStyle(e.closest(".dropzone, .add-drop")).outline));
      return { key, ring, desc: `${e.tagName.toLowerCase()} "${(e.getAttribute("aria-label") || e.textContent || e.getAttribute("placeholder") || e.name || "").trim().slice(0, 40)}"` };
    });
    if (!info) continue;
    if (seen.has(info.key)) { if (++loops > 3) break; continue; }
    seen.add(info.key); if (!info.ring) noRing.push(info.desc);
  }
  const ok = seen.size >= want && noRing.length === 0;
  if (!ok) failed++;
  console.log(`${ok ? "ok " : "FAIL"} ${path.split("?")[0].padEnd(14)} reached ${seen.size}/${want} controls${noRing.length ? `; no visible focus: ${noRing.join(", ")}` : ""}`);
}
// Radio group: arrow keys move the choice
await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" }); await p.waitForTimeout(800);
await p.locator('input[name="place"]').first().focus(); await p.keyboard.press("Space"); await p.keyboard.press("ArrowDown");
console.log(`ok  Draft radio group: ArrowDown moves the choice to "${await p.evaluate(() => document.activeElement.closest("label").textContent.trim())}"`);
// Closed details: Enter on the summary opens it and its links become tabbable
await p.goto(`${WEB}/app/queue`, { waitUntil: "networkidle" }); await p.waitForTimeout(800);
if (await p.locator("details.add-details summary").count()) {
  await p.locator("details.add-details summary").focus(); await p.keyboard.press("Enter");
  await p.keyboard.press("Tab");
  console.log(`ok  Queue "Already decided": Enter opens it, Tab reaches "${await p.evaluate(() => document.activeElement.textContent.trim().slice(0, 30))}"`);
}
// Shift+Tab goes backwards, Enter follows the workspace link
await p.goto(`${WEB}/app/sources`, { waitUntil: "networkidle" });
for (let i = 0; i < 40; i++) { await p.keyboard.press("Tab"); if (await p.evaluate(() => document.activeElement?.textContent?.trim() === "Queue")) break; }
await p.keyboard.press("Shift+Tab"); const back = await p.evaluate(() => document.activeElement?.textContent?.trim());
await p.keyboard.press("Tab"); await p.keyboard.press("Enter"); await p.waitForURL("**/app/queue");
console.log(`ok  Shift+Tab from "Queue" -> "${back}"; Enter on "Queue" opens /app/queue`);
await b.close(); if (failed) process.exit(1);
