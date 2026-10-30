// A real team: invited through the pages, then a draft from writer to reviewer to approver to published.
// At every step the buttons on screen must equal what the API allows that person.
import assert from "node:assert/strict";
import { addApprovedDocument, apiAs, checkDraft, decisionButtons, go, pageAs, registerApi, says, uniqueEmail, WEB } from "./lib.mjs";

const LABEL = { submit: "Send for review", resubmit: "Send for review again", mark_reviewed: "Mark as reviewed", approve: "Approve", request_changes: "Send back for changes", reject: "Reject", publish: "Mark as published" };

/** Everything in the decision panel's button stack is an allowed action, and nothing allowed is missing. */
async function buttonsMatchApi(p, login, reviewId, who) {
  const review = (await apiAs(login)(`/api/reviews/${reviewId}`)).body;
  const expected = review.allowed_actions.filter((a) => LABEL[a]).map((a) => LABEL[a]);
  await go(p, `/app/decide?id=${reviewId}`);
  const shown = (await decisionButtons(p)).filter((b) => Object.values(LABEL).includes(b));
  assert.deepEqual([...shown].sort(), [...expected].sort(), `${who} at ${review.workflow_status}`);
  return review;
}

/** A person opens the invitation link, creates an account, accepts. Answers their page and team session. */
async function joinThroughPages(run, owner, ownerPage, role, name) {
  const email = uniqueEmail(role);
  await go(ownerPage, "/app/team");
  await ownerPage.getByLabel("Email").fill(email);
  await ownerPage.getByLabel("Role", { exact: true }).selectOption(role);
  await ownerPage.getByRole("button", { name: "Create invitation" }).click();
  const link = await ownerPage.getByLabel("Invitation link").inputValue();
  assert.ok(link.startsWith(`${WEB}/invite/accept?token=`), link);

  const p = await pageAs(run, null);
  await p.goto(link);
  await p.getByRole("link", { name: "Create an account" }).click();
  await p.waitForURL("**/login?mode=signup*");
  await p.getByLabel("Your name (optional)").fill(name);
  await p.getByLabel("Work email").fill(email);
  await p.getByLabel(/^Password/).fill(process.env.AUDIT_PASSWORD);
  await p.getByLabel("Confirm password").fill(process.env.AUDIT_PASSWORD);
  await p.getByRole("button", { name: "Create account" }).click();
  await p.waitForURL("**/invite/accept?token=*", { timeout: 30000 });
  await p.getByRole("button", { name: "Accept invitation" }).click();
  await p.getByRole("button", { name: /Open the workspace/ }).click();
  await p.waitForURL("**/app/**");
  await p.waitForLoadState("networkidle");

  // The session the page now holds, so API checks are made as the same person in the same workspace.
  const token = await p.evaluate(() => JSON.parse(localStorage.getItem("audit-ai.session")));
  assert.equal(token.role, role);
  return { p, login: { access_token: token.token, user: { id: token.userId, email }, organisation: token.organisation, role, workspace: token.workspace }, email, name };
}

export default async function journey(run) {
  const owner = await registerApi(uniqueEmail("owner"), "Olive Owner");
  const brand = (await apiAs(owner)("/api/brands")).body[0];
  await addApprovedDocument(owner, brand.id);
  const ownerPage = await pageAs(run, owner);

  const writer = await joinThroughPages(run, owner, ownerPage, "writer", "Wyn Writer");
  const reviewer = await joinThroughPages(run, owner, ownerPage, "reviewer", "Rae Reviewer");
  const approver = await joinThroughPages(run, owner, ownerPage, "approver", "Abi Approver");
  await go(ownerPage, "/app/team");
  await says(ownerPage, "4 members");

  // Writer: can send the draft on, can't approve it.
  const id = await checkDraft(writer.p, "The Lumen Pods last 30 hours on one charge.", "E2E team draft");
  const drafted = await buttonsMatchApi(writer.p, writer.login, id, "writer");
  assert.ok(drafted.allowed_actions.includes("submit"), "writer can submit");
  assert.ok(!drafted.allowed_actions.includes("approve"), "writer can't approve their own draft");
  await writer.p.getByRole("button", { name: "Send for review", exact: true }).click();
  await says(writer.p, /Sent for review\./);
  const bar = writer.p.getByRole("region", { name: "Where this draft stands" });
  await bar.getByText("In review").waitFor();
  assert.match(await bar.innerText(), /Wyn Writer/, "author shown");
  await buttonsMatchApi(writer.p, writer.login, id, "writer");

  // Owner: assigns the reviewer, from real members.
  await buttonsMatchApi(ownerPage, owner, id, "owner");
  await ownerPage.getByLabel("Assigned reviewer").selectOption({ label: "Rae Reviewer" });
  await ownerPage.getByRole("button", { name: "Assign", exact: true }).click();
  await says(ownerPage, /Reviewer assigned\./);
  await ownerPage.getByRole("region", { name: "Where this draft stands" }).getByText("Rae Reviewer").waitFor();

  // Reviewer: marks it reviewed, with a note.
  const inReview = await buttonsMatchApi(reviewer.p, reviewer.login, id, "reviewer");
  assert.ok(inReview.allowed_actions.includes("mark_reviewed"));
  await reviewer.p.getByLabel(/^Note/).fill("Battery claim checked against the spec.");
  await reviewer.p.getByRole("button", { name: "Mark as reviewed" }).click();
  await says(reviewer.p, /Marked as reviewed\./);
  await reviewer.p.getByRole("region", { name: "Where this draft stands" }).getByText("Reviewed", { exact: false }).waitFor();

  // Approver: approves, then records it as published.
  const reviewed = await buttonsMatchApi(approver.p, approver.login, id, "approver");
  assert.ok(reviewed.allowed_actions.includes("approve"), JSON.stringify(reviewed.allowed_actions));
  const ack = approver.p.getByRole("checkbox", { name: /I understand no real check ran/ });
  if (await ack.count()) await ack.check();
  await approver.p.getByRole("button", { name: "Approve", exact: true }).click();
  await says(approver.p, /Saved: Approved/);
  const approved = await buttonsMatchApi(approver.p, approver.login, id, "approver");
  assert.ok(approved.allowed_actions.includes("publish"), JSON.stringify(approved.allowed_actions));
  await approver.p.getByRole("button", { name: "Mark as published" }).click();
  await approver.p.getByRole("dialog").getByRole("button", { name: "Mark as published" }).click();
  await says(approver.p, /Marked as published\./);
  await approver.p.getByRole("region", { name: "Where this draft stands" }).getByText("Published").waitFor();
  assert.equal((await apiAs(owner)(`/api/reviews/${id}`)).body.workflow_status, "published");

  // The Queue shows the team's columns, and names the reviewer.
  await go(ownerPage, "/app/queue");
  await ownerPage.getByText(/Already decided/).click();
  const row = ownerPage.getByRole("row").filter({ hasText: "E2E team draft" });
  await row.waitFor();
  assert.match(await row.innerText(), /Rae Reviewer/);
  assert.match(await row.innerText(), /Published/);

  // Later journeys pick up this team.
  run.shared.team = { owner, writer: writer.login, reviewer: reviewer.login, approver: approver.login, writerEmail: writer.email, reviewId: id };
}
