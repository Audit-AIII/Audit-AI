import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage();
const msgs = []; p.on("console", (m) => { if (/hydrat/i.test(m.text())) msgs.push(m.text().slice(0, 120)); });
for (const u of ["/", "/login"]) await p.goto("http://localhost:3100" + u, { waitUntil: "networkidle" });
console.log("hydration warnings:", msgs.length ? msgs : "none"); await b.close();
