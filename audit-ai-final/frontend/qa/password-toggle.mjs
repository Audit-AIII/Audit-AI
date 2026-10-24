// Eye button on every password field (sign in, create account): toggles show / hide, never submits,
// keyboard reachable with a visible focus ring, announced as pressed. node qa/password-toggle.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const WEB = "http://localhost:3000";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = []; p.on("pageerror", (e) => errors.push(e.message));
let posts = 0; p.on("request", (r) => r.method() === "POST" && posts++);

for (const [path, ids] of [["/login", ["a-password"]], ["/login?mode=signup", ["a-password", "a-confirm"]]]) {
  await p.goto(`${WEB}${path}`, { waitUntil: "networkidle" });
  for (const id of ids) {
    const input = p.locator(`#${id}`);
    const eye = p.locator(`#${id} + .field__eye`);
    await input.fill("s3cret-Pass");
    assert.equal(await input.getAttribute("type"), "password", "hidden by default");
    assert.equal(await eye.getAttribute("aria-label"), "Show password");
    assert.equal(await eye.getAttribute("aria-pressed"), "false");
    await eye.click();
    assert.equal(await input.getAttribute("type"), "text");
    assert.equal(await eye.getAttribute("aria-label"), "Hide password");
    assert.equal(await eye.getAttribute("aria-pressed"), "true");
    assert.equal(await input.inputValue(), "s3cret-Pass", "value kept");
    // keyboard: Tab from the input reaches the eye; Space toggles back
    await input.focus(); await p.keyboard.press("Tab");
    assert.equal(await p.evaluate(() => document.activeElement?.className), "field__eye");
    assert.notEqual(await eye.evaluate((el) => getComputedStyle(el).outlineStyle), "none", "visible focus");
    await p.keyboard.press("Space");
    assert.equal(await input.getAttribute("type"), "password");
    const box = await eye.boundingBox(); assert.ok(box.width >= 44 && box.height >= 44, "44px hit area");
  }
  for (const w of [1440, 390]) {
    await p.setViewportSize({ width: w, height: w === 1440 ? 900 : 844 });
    await p.locator(`#${ids[0]} + .field__eye`).click();
    assert.ok((await p.evaluate(() => document.documentElement.scrollWidth)) <= w, "no horizontal scroll");
    await p.screenshot({ path: `qa/out/password-${path.includes("signup") ? "signup" : "signin"}-${w}.png` });
    await p.locator(`#${ids[0]} + .field__eye`).click();
  }
  await p.setViewportSize({ width: 1440, height: 900 });
  console.log(`ok  ${path}: ${ids.length} password field(s) toggle show/hide, keyboard + aria-pressed, 44px, no scroll at 390`);
}
assert.equal(posts, 0, "the eye button never submits the form");
assert.deepEqual(errors, []); console.log("ok  no form submitted, no page errors"); await b.close();
