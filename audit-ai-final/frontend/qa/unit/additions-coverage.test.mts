// node --experimental-strip-types qa/unit/additions-coverage.test.mts
import assert from "node:assert/strict";
import { coverage } from "../../lib/additions/coverage.ts";

const T = "Meet the Aero 🎧. One charge lasts 24 hours. Price is ₹2,499. Enjoy!";
const cp = (s: string) => Array.from(s).length;
const span = (n: string) => ({ start: cp(T.slice(0, T.indexOf(n))), end: cp(T.slice(0, T.indexOf(n))) + cp(n) });
const f = (id: string, text: string, status: string) =>
  ({ finding_id: id, original_text: text, span: span(text), verification_status: status }) as never;
const c = coverage(T, [f("a", "One charge lasts 24 hours.", "contradicted"), f("b", "Price is ₹2,499.", "supported")]);
assert.deepEqual(c.sentences.map((s) => s.status), ["none", "contradicted", "supported", "none"]);
assert.equal(c.percent, 50);
assert.equal(coverage(T, []).percent, null, "no claims -> no percentage");
const rule = { ...f("r", "Enjoy!", "unverified"), check_type: "rule" } as never;
assert.equal(coverage(T, [rule]).sentences[3].status, "none", "a rule finding never shows as Not proven yet / Matches");
console.log("additions coverage: all assertions passed");
