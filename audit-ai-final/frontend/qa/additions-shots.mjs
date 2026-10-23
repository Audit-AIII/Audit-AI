// Screenshots of an additive page at 1182x937 and 390x844, signed in for real.
//   AUDIT_EMAIL=... AUDIT_PASSWORD=... node qa/additions-shots.mjs <route> [query]
// e.g. node qa/additions-shots.mjs guidelines    or    node qa/additions-shots.mjs coverage "id=..."
import { chromium } from "playwright";

const [route, query = ""] = process.argv.slice(2);
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password } = process.env;
if (!route || !email || !password) throw new Error("usage: AUDIT_EMAIL AUDIT_PASSWORD node qa/additions-shots.mjs <route> [query]");
const WEB = "http://localhost:3000";
const b = await chromium.launch();
const errors = [];
for (const [w, h, tag] of [[1182, 937, "desktop"], [390, 844, "mobile"]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  p.on("pageerror", (e) => errors.push(e.message));
  p.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
  await p.goto(`${WEB}/login?next=${encodeURIComponent(`/app/${route}${query ? `?${query}` : ""}`)}`, { waitUntil: "networkidle" });
  await p.fill("#a-email", email);
  await p.fill("#a-password", password);
  await p.click("button[type=submit]");
  await p.waitForURL(`**/app/${route}**`, { timeout: 20000 });
  await p.waitForFunction(() => getComputedStyle(document.querySelector(".sandwave")).visibility === "hidden", null, { timeout: 15000 });
  await p.waitForLoadState("networkidle");
  await p.waitForTimeout(800);
  await p.screenshot({ path: `qa/out/add-${route}-${tag}.png`, fullPage: tag === "mobile" });
  const over = await p.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  console.log(`${tag}: qa/out/add-${route}-${tag}.png  horizontal overflow=${over}px`);
  await p.close();
}
console.log(errors.length ? `ERRORS:\n  ${errors.join("\n  ")}` : "no page/console errors");
await b.close();
