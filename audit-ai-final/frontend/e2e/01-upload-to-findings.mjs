// Upload a draft and see an honest result; then a checked draft's summary and finding cards.
import assert from "node:assert/strict";
import { go, main, pageAs, reviewsOf, says, WEB } from "./lib.mjs";

export default async function journey(run) {
  const p = await pageAs(run, null);

  // Signing in through the form, as a person would.
  await p.goto(`${WEB}/login?next=${encodeURIComponent("/app/draft")}`);
  await p.getByLabel("Work email").fill("asha@seed.inkloom.demo");
  await p.getByRole("textbox", { name: "Password" }).fill(process.env.AUDIT_PASSWORD);
  await p.getByRole("button", { name: "Sign in" }).click();
  await p.waitForURL("**/app/draft", { timeout: 30000 });
  await p.waitForLoadState("networkidle");

  // A text file through the upload control.
  await p.locator('input[type="file"]').setInputFiles({ name: "e2e-draft.txt", mimeType: "text/plain", buffer: Buffer.from("The Lumen Pods last 30 hours on one charge.") });
  await p.getByLabel("Title (optional)").fill("E2E upload");
  await p.waitForFunction(() => !document.querySelector('button[type="submit"]')?.disabled);
  await p.getByRole("button", { name: /Check my draft/ }).click();
  await p.waitForURL("**/app/review?id=*", { timeout: 90000 });
  await p.waitForLoadState("networkidle");

  // No AI provider here, so the result must say nothing was really checked.
  await says(p, "Placeholder, not a real check.");
  assert.match(await main(p).innerText(), /Placeholder/);

  // A review with real findings: the summary is the server's, and the card has every part.
  const reviews = await reviewsOf(run.shared.asha);
  const seeded = reviews.find((r) => r.status === "needs_human_review" && r.findings.some((f) => f.verification_status === "contradicted"));
  assert.ok(seeded, "the seed has a contradicted finding");
  await go(p, `/app/review?id=${seeded.id}`);
  const strip = p.getByRole("region", { name: "What the checker found" });
  await strip.waitFor();
  const stripText = await strip.innerText();
  assert.match(stripText, new RegExp(`${seeded.summary_counts.contradicted}\\s+≠ Doesn’t match`));
  assert.match(stripText, new RegExp(`${seeded.summary_counts.supported}\\s+✓ Matches`));

  const finding = seeded.findings.find((f) => f.verification_status === "contradicted");
  await p.getByRole("region", { name: "Problems found" }).getByRole("button", { name: new RegExp(finding.original_text.slice(0, 20).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).click();
  const detail = await p.getByRole("region", { name: "Why it was flagged" }).innerText();
  assert.match(detail, /Doesn’t match/);
  assert.match(detail, /severity|Low|Medium|High|Critical/i);
  assert.match(detail, /Disagrees/i, "the evidence says how it relates");
  assert.ok(detail.includes(finding.evidence[0].quote), "the quote from the document");
  if (finding.explanation) assert.ok(detail.includes(finding.explanation), "the explanation");
}
