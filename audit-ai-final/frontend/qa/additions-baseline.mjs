// Proves existing pages are pixel-identical before/after the additive pages.
//   node qa/additions-baseline.mjs save     -> writes qa/out/baseline/*.png
//   node qa/additions-baseline.mjs compare  -> compares current screenshots with the saved ones
// Needs AUDIT_EMAIL / AUDIT_PASSWORD (a real account on the local backend). Animations are frozen.
import { chromium } from "playwright";
import fs from "node:fs";

const mode = process.argv[2] ?? "compare";
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password } = process.env;
if (!email || !password) throw new Error("set AUDIT_EMAIL, AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const DIR = "qa/out/baseline";
fs.mkdirSync(DIR, { recursive: true });

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1182, height: 937 }, reducedMotion: "reduce" });
const p = await ctx.newPage();
const shot = async (name) => {
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(1200);
  return p.screenshot({ animations: "disabled", caret: "hide" });
};
const pages = [];
await p.goto(`${WEB}/login`, { waitUntil: "networkidle" });
pages.push(["login", await shot()]);
await p.fill("#a-email", email);
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/sources", { timeout: 20000 });
await p.waitForSelector(".approved-count");
await p.waitForFunction(() => getComputedStyle(document.querySelector(".sandwave")).visibility === "hidden");
pages.push(["sources", await shot()]);
for (const s of ["draft", "decide", "record"]) {
  await p.goto(`${WEB}/app/${s}`, { waitUntil: "networkidle" });
  pages.push([s, await shot()]);
}

let same = true;
for (const [name, buf] of pages) {
  const file = `${DIR}/${name}.png`;
  if (mode === "save") {
    fs.writeFileSync(file, buf);
    console.log(`saved ${file}`);
  } else {
    const before = fs.readFileSync(file);
    const eq = before.equals(buf);
    same &&= eq;
    if (!eq) fs.writeFileSync(`${DIR}/${name}.after.png`, buf);
    console.log(`${eq ? "identical" : "DIFFERENT"}  ${name}`);
  }
}
await b.close();
if (!same) process.exit(1);
