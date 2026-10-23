// Run: node --experimental-strip-types qa/unit/codepoints.test.mts
import assert from "node:assert/strict";
import { cpToUtf16, segment, spanToUtf16 } from "../../lib/text/codepoints.ts";

// Python computes spans in code points: "🎧 " is 2 code points but 3 UTF-16 units.
const text = "🎧 Aero lasts 24 hours. Made in 🇮🇳 India.";
const cps = Array.from(text);
const want = "lasts 24 hours";
const start = cps.join("").indexOf(want); // UTF-16 index (wrong unit on purpose)
const cpStart = Array.from(text.slice(0, start)).length; // what the backend would send
const span = { start: cpStart, end: cpStart + Array.from(want).length };

assert.notEqual(text.slice(span.start, span.end), want, "naive slicing must be wrong for emoji text");
const u = spanToUtf16(text, span);
assert.equal(text.slice(u.start, u.end), want);
assert.equal(text.slice(u.start, u.end), cps.slice(span.start, span.end).join("")); // contract's reference conversion

// Flag emoji = 2 code points (4 UTF-16 units); span covering "India"
const india = cps.indexOf("I", cps.indexOf("🇳"));
const s2 = spanToUtf16(text, { start: india, end: india + 5 });
assert.equal(text.slice(s2.start, s2.end), "India");

assert.equal(cpToUtf16(text, 9999), text.length, "clamps past the end");
assert.equal(cpToUtf16("", 3), 0);

// Segments: overlap kept, full text preserved, no empty runs
const segs = segment(text, [
  { span, item: "a" },
  { span: { start: span.start + 6, end: span.end + 2 }, item: "b" },
]);
assert.equal(segs.map((s) => s.text).join(""), text);
assert.ok(segs.every((s) => s.text.length > 0));
assert.deepEqual(segs.find((s) => s.text === "24 hours")?.marks, ["a", "b"]);
console.log("codepoints: all assertions passed");
