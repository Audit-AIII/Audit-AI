// Alone in a workspace: send back, approve, and a refusal when the draft changed under the page.
import assert from "node:assert/strict";
import { addApprovedDocument, apiAs, checkDraft, decisionButtons, go, main, pageAs, registerApi, says, uniqueEmail } from "./lib.mjs";

const stubAck = async (p) => {
  const box = p.getByRole("checkbox", { name: /I understand no real check ran/ });
  if (await box.count()) await box.check();
};

export default async function journey(run) {
  const me = await registerApi(uniqueEmail("solo"), "Solo");
  const brand = (await apiAs(me)("/api/brands")).body[0];
  await addApprovedDocument(me, brand.id);
  const p = await pageAs(run, me);

  // Send back with a note: the status and the record come from the server.
  const first = await checkDraft(p, "The Lumen Pods last 30 hours on one charge.", "E2E send back");
  await go(p, `/app/decide?id=${first}`);
  const buttons = await decisionButtons(p);
  assert.ok(buttons.includes("Approve") && buttons.includes("Reject"), `solo controls: ${buttons}`);
  assert.ok(!buttons.includes("Send for review"), "nobody to send it to");
  await says(p, "Solo sign-off: you are the only member, so you decide.");
  await p.getByLabel(/^Note/).fill("Fix the battery claim.");
  await p.getByRole("button", { name: "Send back for changes" }).click();
  await says(p, /Saved: Changes requested/);
  await go(p, `/app/record?id=${first}`);
  const history = p.getByRole("region", { name: "History" });
  await history.getByText("Fix the battery claim.").waitFor();
  assert.match(await history.innerText(), /Sent back for changes/);
  assert.equal((await apiAs(me)(`/api/reviews/${first}`)).body.status, "changes_requested");

  // Approve a fresh draft.
  const second = await checkDraft(p, "The Lumen Pods last 24 hours on one charge.", "E2E approve");
  await go(p, `/app/decide?id=${second}`);
  await stubAck(p);
  await p.getByRole("button", { name: "Approve", exact: true }).click();
  await says(p, /Saved: Approved/);
  assert.match(await main(p).innerText(), /Approved/);
  assert.equal((await apiAs(me)(`/api/reviews/${second}`)).body.workflow_status, "approved");

  // A new version appears while the page is open: Approve is refused, and the note stays.
  const third = await checkDraft(p, "The Lumen Pods last 20 hours on one charge.", "E2E stale");
  await go(p, `/app/decide?id=${third}`);
  await stubAck(p);
  await p.getByLabel(/^Note/).fill("I typed this before the refusal.");
  const review = (await apiAs(me)(`/api/reviews/${third}`)).body;
  const saved = await apiAs(me)(`/api/content/${review.content_item_id}/versions`, { method: "POST", body: { text: "A newer version." } });
  assert.equal(saved.status, 201, JSON.stringify(saved.body));
  await p.getByRole("button", { name: "Approve", exact: true }).click();
  const alert = p.getByRole("alert").filter({ hasText: /newer version|stale|latest|current/i }).first();
  await alert.waitFor();
  assert.match(await alert.innerText(), /Reference/, "the request id is shown");
  assert.equal(await p.getByLabel(/^Note/).inputValue(), "I typed this before the refusal.");
}
