// Correct a draft: safer wording is labelled, a new version is saved, and the old one can't be approved.
import assert from "node:assert/strict";
import { apiAs, go, main, pageAs, reviewsOf, says } from "./lib.mjs";

const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export default async function journey(run) {
  const { asha } = run.shared;
  const reviews = await reviewsOf(asha);
  const target = reviews.find((r) => r.status === "needs_human_review" && r.is_current_version);
  assert.ok(target, "the seed has an open draft");
  const p = await pageAs(run, asha);

  // The seed has no safer wording today, so the label is checked only when one exists.
  // qa/safer-wording.mjs covers that label against the API's documented shape.
  const safer = reviews.flatMap((r) => r.findings.map((f) => ({ f, r }))).find(({ f }) => f.safer_wording);
  if (safer) {
    await go(p, `/app/review?id=${safer.r.id}`);
    await p.getByRole("region", { name: "Problems found" }).getByRole("button", { name: new RegExp(escape(safer.f.original_text.slice(0, 20))) }).click();
    await says(p, "Safer wording, not evidence-backed");
  }

  await go(p, `/app/review-edit?id=${target.id}`);
  const box = p.getByLabel("Your new version");
  await box.waitFor();
  await box.fill(`${await box.inputValue()} Edited by the E2E test.`);
  await p.getByRole("button", { name: "Save as new version" }).click();
  const next = target.version_number + 1;
  await p.getByRole("link", { name: new RegExp(`Open version ${next}’s review`) }).waitFor({ timeout: 90000 });

  const after = (await apiAs(asha)(`/api/reviews/${target.id}`)).body;
  assert.equal(after.is_current_version, false);
  assert.ok(!after.allowed_actions.includes("approve"), "the old version can't be approved");

  await go(p, `/app/decide?id=${target.id}`);
  await says(p, /newer version of this draft exists/);
  assert.match(await main(p).innerText(), new RegExp(`latest is version ${next}`));
  assert.equal(await p.getByRole("button", { name: "Approve", exact: true }).count(), 0);
  await p.getByRole("link", { name: "Open the latest version" }).click();
  await p.waitForURL("**/app/decide?id=*");
  assert.notEqual(new URL(p.url()).searchParams.get("id"), target.id);
}
