// node --experimental-strip-types qa/unit/additions-diff.test.mts
import assert from "node:assert/strict";
import { wordDiff } from "../../lib/additions/diff.ts";

const before = "One charge lasts 24 hours. Price ₹2,499.";
const after = "One charge lasts 12 hours. Price ₹2,499.";
const d = wordDiff(before, after);
assert.equal(d.filter((p) => p.kind !== "ins").map((p) => p.text).join(""), before);
assert.equal(d.filter((p) => p.kind !== "del").map((p) => p.text).join(""), after);
assert.deepEqual(d.filter((p) => p.kind !== "same").map((p) => `${p.kind}:${p.text}`), ["del:24", "ins:12"]);
assert.deepEqual(wordDiff("same", "same"), [{ kind: "same", text: "same" }]);
assert.deepEqual(wordDiff("", "new"), [{ kind: "ins", text: "new" }]);
console.log("additions diff: all assertions passed");
