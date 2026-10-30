// The record of the team draft from journey 4, and the workspace log for owners only.
import assert from "node:assert/strict";
import { go, pageAs } from "./lib.mjs";

export default async function journey(run) {
  const { team } = run.shared;
  assert.ok(team, "needs journey 04");

  const owner = await pageAs(run, team.owner);
  await go(owner, `/app/record?id=${team.reviewId}`);
  const history = owner.getByRole("region", { name: "History" });
  await history.getByText("Marked as published").waitFor();
  const text = await history.innerText();
  for (const step of ["Marked as published", "Approved", "Marked as reviewed", "Reviewer assigned", "Sent for review", "Routing decision", "Draft created"]) assert.ok(text.includes(step), step);
  for (const person of ["Wyn Writer", "Rae Reviewer", "Abi Approver", "Olive Owner"]) assert.ok(text.includes(person), person);
  assert.ok(text.includes("Battery claim checked against the spec."), "the reviewer's note");

  await go(owner, "/app/audit");
  await owner.getByRole("main").getByText("Invitation accepted").first().waitFor();
  assert.match(await owner.getByRole("main").innerText(), /Invitation created/);

  // The owner has the link; a writer doesn't, and the page refuses them anyway.
  await owner.getByRole("button", { name: /Workspace|Audit log/ }).first().click();
  await owner.getByRole("link", { name: "Audit log" }).first().waitFor();
  const writer = await pageAs(run, team.writer);
  await go(writer, "/app/queue");
  await writer.getByRole("button", { name: /Queue/ }).first().click();
  assert.equal(await writer.getByRole("link", { name: "Audit log" }).count(), 0);
  await go(writer, "/app/audit");
  await writer.getByRole("main").getByText("Only workspace owners can see this.").waitFor();
}
