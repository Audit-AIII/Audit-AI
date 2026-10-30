// The server refuses, and the page says why. The page is opened while an action is allowed, and the
// rule changes behind it, so the refusal comes from the real backend with no mocking.
import assert from "node:assert/strict";
import { addApprovedDocument, apiAs, checkDraft, go, joinApi, pageAs, registerApi, uniqueEmail } from "./lib.mjs";

export default async function journey(run) {
  const owner = await registerApi(uniqueEmail("refuse"), "Rhea Owner");
  const brand = (await apiAs(owner)("/api/brands")).body[0];
  await addApprovedDocument(owner, brand.id);
  const p = await pageAs(run, owner);

  const id = await checkDraft(p, "The Lumen Pods last 30 hours on one charge.", "E2E self approval");
  await go(p, `/app/decide?id=${id}`);
  const ack = p.getByRole("checkbox", { name: /I understand no real check ran/ });
  if (await ack.count()) await ack.check();
  assert.equal(await p.getByRole("button", { name: "Approve", exact: true }).count(), 1, "alone, so they could approve");

  // Someone who can approve joins while the page is open. Now it isn't the author's call.
  await joinApi(owner, "approver", "Ana Approver");
  await p.getByRole("button", { name: "Approve", exact: true }).click();
  const alert = p.getByRole("alert").filter({ hasText: /someone else has to approve|has to be reviewed/ }).first();
  await alert.waitFor();
  assert.match(await alert.innerText(), /Reference/);

  // Reload: the page now agrees with the server and doesn't offer it.
  await go(p, `/app/decide?id=${id}`);
  assert.equal(await p.getByRole("button", { name: "Approve", exact: true }).count(), 0);

  // The refusal is on the record, with who tried.
  const review = (await apiAs(owner)(`/api/reviews/${id}`)).body;
  await go(p, `/app/record?id=${id}`);
  await p.getByRole("region", { name: "History" }).getByText("Approval refused").waitFor();

  // Self-review and self-approval, directly: the same rules hold without the page.
  const selfApprove = await apiAs(owner)(`/api/content-versions/${review.content_version_id}/approve`, { method: "POST" });
  assert.ok([403, 409].includes(selfApprove.status), `approve answered ${selfApprove.status}`);
  const selfReview = await apiAs(owner)(`/api/content/${review.content_item_id}/mark-reviewed`, { method: "POST", body: { content_version_id: review.content_version_id } });
  assert.ok([403, 409].includes(selfReview.status), `mark-reviewed answered ${selfReview.status}`);
}
