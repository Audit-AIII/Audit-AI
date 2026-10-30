// node --experimental-strip-types qa/unit/invite-switch.test.mts
// Where sign-in may send someone, and what switching workspace clears from this browser.
import assert from "node:assert/strict";
import { safeNext } from "../../lib/safeNext.ts";
import { clearWorkspaceMemory } from "../../lib/workspace.ts";

// Allowed: workspace paths and exactly the invitation page.
assert.equal(safeNext("/app/queue"), "/app/queue");
assert.equal(safeNext("/app?x=1"), "/app?x=1");
assert.equal(safeNext("/invite/accept?token=abc-_123"), "/invite/accept?token=abc-_123");
assert.equal(safeNext("/invite/accept"), "/invite/accept");

// Refused: other sites and any other path, however they're dressed up.
for (const bad of [
  null,
  "",
  "//evil.example",
  "https://evil.example",
  "/invite/accept/../x",
  "/invite/accept/../../evil",
  "/invite/acceptance",
  "/invite/accept#x",
  "/invite/accept?x=\\evil",
  "/invite",
  "/\\evil.example",
  "/login",
  "javascript:alert(1)",
]) {
  assert.equal(safeNext(bad), "/app", String(bad));
}

// Switching keeps the session and forgets everything tied to the old workspace.
const store = new Map<string, string>([
  ["audit-ai.session", "keep"],
  ["audit-ai.active-brand", "b1"],
  ["audit-ai.additions.brand", "b1"],
  ["audit-ai.last-review", "r1"],
  ["audit-ai.review-text.r1", "draft text"],
  ["audit-ai.review-text-index", "[]"],
  ["audit-ai.decision.r1", "{}"],
  ["other-app.setting", "keep"],
]);
(globalThis as { window?: unknown }).window = {
  localStorage: {
    get length() {
      return store.size;
    },
    key: (i: number) => [...store.keys()][i] ?? null,
    removeItem: (k: string) => store.delete(k),
  },
};
clearWorkspaceMemory();
assert.deepEqual([...store.keys()].sort(), ["audit-ai.session", "other-app.setting"]);

// Blocked storage must not break a switch.
(globalThis as { window?: unknown }).window = {
  get localStorage() {
    throw new Error("blocked");
  },
};
clearWorkspaceMemory();

console.log("invite and switch: all assertions passed");
