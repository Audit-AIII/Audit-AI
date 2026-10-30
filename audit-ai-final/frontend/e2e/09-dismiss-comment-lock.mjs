// Dismiss and restore a finding, comment on it, and protect a phrase with Intent-lock.
import assert from "node:assert/strict";
import { apiAs, checkedOpenReview, go, pageAs, reviewsOf } from "./lib.mjs";

export default async function journey(run) {
  const { asha } = run.shared;
  const target = checkedOpenReview(await reviewsOf(asha));
  assert.ok(target);
  const p = await pageAs(run, asha);
  await go(p, `/app/review?id=${target.id}`);
  const detail = p.getByRole("region", { name: "Why it was flagged" });

  // Dismiss: the verdict stays, and the count stays with it.
  const before = await p.getByRole("region", { name: "What the checker found" }).innerText();
  await detail.getByRole("button", { name: "Dismiss this finding" }).click();
  await detail.getByRole("button", { name: "Restore" }).waitFor();
  const strip = p.getByRole("region", { name: "What the checker found" });
  await strip.getByText("1 dismissed").waitFor();
  const countOf = (text) => text.match(/(\d+)\s+\? Not proven yet/)?.[1];
  assert.equal(countOf(await strip.innerText()), countOf(before), "dismissed findings stay counted");
  await detail.getByRole("button", { name: "Restore" }).click();
  await detail.getByRole("button", { name: "Dismiss this finding" }).waitFor();

  // Comment.
  const comment = `E2E comment ${Date.now()}`;
  await detail.getByLabel("Add a comment").fill(comment);
  await detail.getByRole("button", { name: "Add comment" }).click();
  await detail.getByText(comment).waitFor();
  await go(p, `/app/review?id=${target.id}`);
  await p.getByRole("region", { name: "Why it was flagged" }).getByText(comment).waitFor();

  // Intent-lock: mark a phrase, then removing it warns before saving.
  await go(p, `/app/review-edit?id=${target.id}`);
  const box = p.getByLabel("Your new version");
  await box.waitFor();
  const text = await box.inputValue();
  const phrase = text.split(" ").slice(0, 2).join(" ");
  await box.evaluate((el, n) => {
    el.focus();
    el.setSelectionRange(0, n);
  }, phrase.length);
  await p.getByRole("button", { name: /Mark must-keep text/ }).click();
  const list = p.getByRole("list", { name: "Must-keep text" });
  await list.getByText(phrase).waitFor();
  const saved = (await apiAs(asha)(`/api/content-versions/${target.content_version_id}/locks`)).body;
  assert.ok(saved.locked_phrases.includes(phrase), "saved on the server");

  await box.fill(text.replace(phrase, "Something else"));
  let warned = "";
  p.once("dialog", async (d) => {
    warned = d.message();
    await d.dismiss();
  });
  await p.getByRole("button", { name: "Save as new version" }).click();
  await p.waitForFunction(() => true);
  assert.ok(warned.includes(phrase), `warned: ${warned}`);
  assert.equal((await apiAs(asha)(`/api/reviews/${target.id}`)).body.is_current_version, true, "declining saves nothing");

  // Leave the seed's review as it was.
  await p.getByRole("button", { name: `Unlock ${phrase}` }).click();
  await list.waitFor({ state: "detached" });
}
