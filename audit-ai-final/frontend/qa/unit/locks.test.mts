// node --experimental-strip-types qa/unit/locks.test.mts
// Fixtures: services/api/API.md "Intent-lock" (["₹2,499", "Lumen Pods"]) and the engine rule
// "a phrase that occurs n times must still occur n times" (inkloom_verify.intent_lock).
import assert from "node:assert/strict";
import { brokenBy, missingIn } from "../../lib/additions/locks.ts";

const locks = ["₹2,499", "Lumen Pods"];
const text = "Lumen Pods cost ₹2,499. Lumen Pods last 24 hours.";
assert.deepEqual(brokenBy("Lumen Pods cost ₹2,499.", "Lumen Pods cost under ₹3,000.", locks), ["₹2,499"]);
assert.deepEqual(brokenBy("Lumen Pods cost ₹2,499.", "Lumen Pods now cost ₹2,499.", locks), []);
assert.deepEqual(brokenBy("They cost ₹2,499.", "They cost ₹2,499.", ["lumen pods"]), [], "case-sensitive and only what the text had");
assert.deepEqual(missingIn(text, text, locks), []);
assert.deepEqual(missingIn(text, "Lumen Pods cost ₹2,499. They last 24 hours.", locks), ["Lumen Pods"], "2 copies -> 1 copy is a loss");
assert.deepEqual(missingIn(text, "lumen pods cost ₹2,499. lumen pods last 24 hours.", locks), ["Lumen Pods"], "exact case");
assert.deepEqual(missingIn("Old text.", "New text with Lumen Pods.", ["Lumen Pods", "₹2,499"]), ["₹2,499"], "a lock not in the checked text must still be there once");
console.log("locks: all assertions passed");
