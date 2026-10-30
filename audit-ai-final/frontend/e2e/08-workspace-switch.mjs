// Switching workspace: the team's work never shows in the person's own workspace.
import assert from "node:assert/strict";
import { go, pageAs, reviewsOf } from "./lib.mjs";

export default async function journey(run) {
  const { team } = run.shared;
  assert.ok(team, "needs journey 04");
  const p = await pageAs(run, team.writer);

  await go(p, "/app/queue");
  const teamReview = (await reviewsOf(team.writer)).find((r) => r.id === team.reviewId);
  await p.getByRole("main").getByText(teamReview.title).first().waitFor({ state: "attached" });
  await p.evaluate((id) => {
    localStorage.setItem("audit-ai.last-review", id);
    localStorage.setItem(`audit-ai.review-text.${id}`, "team draft text");
  }, team.reviewId);

  await p.getByRole("button", { name: /Signed in as/ }).click();
  const switcher = p.getByRole("navigation", { name: "Switch workspace" });
  await switcher.waitFor();
  assert.match(await switcher.innerText(), /✓/, "marks the current one");
  await switcher.getByRole("button").first().click();
  // Switching reloads at /app, which goes to the dashboard.
  await p.waitForURL("**/app/insights");
  await p.waitForLoadState("networkidle");

  const stored = await p.evaluate(() => ({ last: localStorage.getItem("audit-ai.last-review"), keys: Object.keys(localStorage).filter((k) => k.startsWith("audit-ai.review-text")), s: JSON.parse(localStorage.getItem("audit-ai.session")) }));
  assert.equal(stored.last, null);
  assert.deepEqual(stored.keys, []);
  assert.notEqual(stored.s.organisation.id, team.owner.organisation.id);
  assert.equal(stored.s.role, "owner");

  await go(p, "/app/queue");
  assert.doesNotMatch(await p.getByRole("main").innerText(), new RegExp(teamReview.title));

  // The team's review can't be opened from here either.
  await go(p, `/app/review?id=${team.reviewId}`);
  await p.getByRole("main").getByText(/another workspace/).waitFor();
}
