// node --experimental-strip-types qa/unit/governance.test.mts
// Fixtures: copies of contract/examples/governance_*.json (docs/governance.md section 9).
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { actionErrorText, invitationLook, isAllowed, riskLook, roleLook, routingText, workflowLook } from "../../lib/additions/governance.ts";

const fixtures = new URL("../fixtures/governance/", import.meta.url);
const contract = new URL("../../../../contract/examples/", import.meta.url);
const read = (dir: URL, name: string) => JSON.parse(readFileSync(new URL(name, dir), "utf8"));
const fixture = (name: string) => read(fixtures, `governance_${name}.json`);

// The copies must not drift from the contract (skipped when only the frontend folder is present).
if (existsSync(contract)) {
  for (const name of readdirSync(contract).filter((n) => n.startsWith("governance_"))) {
    assert.deepEqual(read(fixtures, name), read(contract, name), `${name} differs from the contract`);
  }
}

// Workflow: every documented status has its own word; unknown reads "In progress"; missing isn't a status.
for (const status of ["draft", "submitted", "in_review", "needs_changes", "reviewed", "approved", "rejected", "published", "blocked"]) {
  assert.notEqual(workflowLook(status).label, "In progress", status);
}
assert.equal(workflowLook("escalated").label, "In progress");
assert.equal(workflowLook(null).label, "Not provided");
assert.equal(workflowLook(undefined).label, "Not provided");

// Risk: null is not the same as nothing found.
assert.equal(riskLook(null).label, "Not assessed yet");
assert.equal(riskLook("clean").label, "None found");
assert.equal(riskLook("severe").label, "Severe");

// Role and invitation: legacy and unknown values never crash and are shown readably.
assert.equal(roleLook("admin").label, "Owner");
assert.equal(roleLook("legal_reviewer").label, "Legal reviewer");
assert.equal(invitationLook("pending").label, "Pending");
assert.equal(invitationLook("on_hold").label, "On hold");

// Every value in the example payloads has a real look.
for (const name of ["review_item_personal", "review_item_team_approver", "review_item_team_writer"]) {
  const r = fixture(name);
  assert.notEqual(workflowLook(r.workflow_status).label, "In progress", name);
  assert.notEqual(riskLook(r.risk_level).glyph, "?", name);
  assert.equal(typeof r.summary_counts.tone, "number", name);
}
for (const m of fixture("members").members) assert.notEqual(roleLook(m.role).glyph, "?", m.role);
for (const i of fixture("invitations_list").items) assert.notEqual(invitationLook(i.status).glyph, "?", i.status);

// allowed_actions: the writer example has no approve; the approver example does.
assert.equal(isAllowed(fixture("review_item_team_writer").allowed_actions, "approve"), false);
assert.equal(isAllowed(fixture("review_item_team_approver").allowed_actions, "approve"), true);
// Missing = older backend, keep today's behaviour. Empty = nothing allowed.
assert.equal(isAllowed(undefined, "approve"), true);
assert.equal(isAllowed([], "approve"), false);

// Errors: every example has readable text, and none is the raw code.
for (const { http_status, body } of fixture("errors")) {
  const text = actionErrorText({ status: http_status, code: body.error.code, message: body.error.message }, "fallback");
  assert.notEqual(text, "fallback", body.error.code);
  assert.ok(!text.includes(body.error.code), body.error.code);
  assert.match(text, /^[A-Z].*[.!?]$/, body.error.code);
}
assert.equal(actionErrorText({ status: 403, code: "NEW_RULE", message: "your role cannot do this" }, "fallback"), "Your role cannot do this.");
assert.equal(actionErrorText({ status: 0, code: "NETWORK_ERROR", message: "network error" }, "fallback"), "fallback");
assert.equal(actionErrorText({ status: 500, code: "INTERNAL_ERROR", message: "boom" }, "fallback"), "fallback");

// Routing text: solo sign-off has no reviewer, so that part isn't shown. A team sees it all.
const routed = "1 claim has no evidence either way, so a reviewer must check this draft before it can be approved.";
assert.equal(routingText(routed, true), "1 claim has no evidence either way.");
assert.equal(routingText(routed, false), routed);
assert.equal(routingText("Something new.", true), "Something new.", "other wording passes through");

console.log("governance: all assertions passed");
