import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage();
await p.goto("https://relevovinco.com", { waitUntil: "networkidle" });
console.log(await p.evaluate(() => document.querySelector("body > svg").outerHTML));
await b.close();
