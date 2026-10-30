// Links that stop working, the wrong person, role changes, removal, and the last owner rule.
import assert from "node:assert/strict";
import { apiAs, go, joinApi, pageAs, registerApi, signInApi, uniqueEmail, WEB } from "./lib.mjs";

const inviteThroughPage = async (p, email, role = "writer") => {
  await go(p, "/app/team");
  await p.getByLabel("Email").fill(email);
  await p.getByLabel("Role", { exact: true }).selectOption(role);
  await p.getByRole("button", { name: "Create invitation" }).click();
  return p.getByLabel("Invitation link").inputValue();
};

export default async function journey(run) {
  const owner = await registerApi(uniqueEmail("manage"), "Mo Owner");
  const p = await pageAs(run, owner);
  const ben = await signInApi("ben@seed.inkloom.demo");

  // Revoked: the link says so.
  const revokedEmail = uniqueEmail("revoked");
  const revokedLink = await inviteThroughPage(p, revokedEmail);
  const row = p.getByRole("listitem").filter({ hasText: revokedEmail });
  await row.getByRole("button", { name: "Revoke" }).click();
  await p.getByRole("dialog").getByRole("button", { name: "Revoke" }).click();
  await row.getByText("Revoked").waitFor();
  const visitor = await pageAs(run, ben);
  await visitor.goto(revokedLink);
  await visitor.getByRole("button", { name: "Accept invitation" }).click();
  await visitor.getByRole("alert").filter({ hasText: "withdrawn" }).waitFor();

  // Wrong email: says so and offers a way forward, staying on the invitation.
  const wrongLink = await inviteThroughPage(p, uniqueEmail("wrong"));
  await visitor.goto(wrongLink);
  await visitor.getByRole("button", { name: "Accept invitation" }).click();
  await visitor.getByRole("alert").filter({ hasText: "different email" }).waitFor();
  await visitor.getByRole("button", { name: "Sign out and use that email" }).click();
  await visitor.getByRole("link", { name: "Sign in" }).waitFor();
  assert.ok(visitor.url().startsWith(`${WEB}/invite/accept?token=`));

  // Change a role and remove someone, on the page; the API agrees.
  const member = await joinApi(owner, "writer", "Tess Teammate");
  await go(p, "/app/team");
  await p.getByLabel("Role for Tess Teammate").selectOption("reviewer");
  await p.getByRole("row").filter({ hasText: "Tess Teammate" }).getByText("Reviewer", { exact: false }).first().waitFor();
  const afterChange = (await apiAs(owner)("/api/workspace/members")).body.members.find((m) => m.user.id === member.user.id);
  assert.equal(afterChange.role, "reviewer");

  await p.getByRole("row").filter({ hasText: "Tess Teammate" }).getByRole("button", { name: "Remove" }).click();
  await p.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
  await p.getByRole("row").filter({ hasText: "Tess Teammate" }).waitFor({ state: "detached" });
  assert.equal((await apiAs(member)("/api/workspace/members")).status, 401, "their access ended");

  // Your own row offers nothing, and the server refuses it anyway. The page can't reach this refusal.
  assert.equal(await p.getByRole("row").filter({ hasText: "(you)" }).getByRole("button", { name: "Remove" }).count(), 0);
  assert.equal(await p.getByLabel("Role for Mo Owner").count(), 0);
  const lastOwner = await apiAs(owner)(`/api/workspace/members/${owner.user.id}`, { method: "DELETE" });
  assert.equal(lastOwner.status, 409);
  assert.equal(lastOwner.body.error.code, "LAST_OWNER_REQUIRED");
}
