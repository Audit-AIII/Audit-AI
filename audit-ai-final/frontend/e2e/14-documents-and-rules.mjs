// Documents, brand rules, the editor's re-check and Coverage, all through the pages.
import assert from "node:assert/strict";
import { apiAs, checkDraft, go, main, pageAs, registerApi, says, uniqueEmail } from "./lib.mjs";

const textFile = (name, text) => ({ name, mimeType: "text/plain", buffer: Buffer.from(text) });

export default async function journey(run) {
  const me = await registerApi(uniqueEmail("docs"), "Dee Docs");
  const api = apiAs(me);
  const brand = (await api("/api/brands")).body[0];
  const p = await pageAs(run, me);

  // Upload and approve a document.
  await go(p, "/app/guidelines");
  await main(p).getByText("No documents yet").waitFor();
  await p.getByRole("region", { name: "Add a document" }).locator('input[type="file"]').setInputFiles(textFile("fact-sheet.txt", "The Lumen Pods last 24 hours on one charge."));
  await p.getByLabel("Document name").fill("Fact sheet");
  await p.getByRole("button", { name: "Upload and approve" }).click();
  const docs = p.getByRole("list", { name: "Documents" });
  const row = docs.getByRole("listitem").filter({ hasText: "Fact sheet" });
  await row.getByText("Approved").waitFor();
  await row.getByText("Version 1").waitFor();

  // A new version keeps its approval.
  await row.getByRole("button", { name: /Upload new version/ }).click();
  const versionDialog = p.getByRole("dialog", { name: "Upload a new version" });
  await versionDialog.locator('input[type="file"]').setInputFiles(textFile("fact-sheet-2.txt", "The Lumen Pods last 26 hours on one charge."));
  await versionDialog.getByRole("button", { name: "Upload version" }).click();
  await row.getByText("Version 2").waitFor();
  await row.getByText("Approved").waitFor();

  // A second document, then withdraw the first: it stops being used.
  await p.getByRole("region", { name: "Add a document" }).locator('input[type="file"]').setInputFiles(textFile("guide.txt", "Always call it the Lumen Pods."));
  await p.getByLabel("Document name").fill("Brand guide");
  await p.getByRole("button", { name: "Upload and approve" }).click();
  const guide = docs.getByRole("listitem").filter({ hasText: "Brand guide" });
  await guide.getByText("Approved").waitFor();
  await row.getByRole("button", { name: /Withdraw/ }).click();
  const withdraw = p.getByRole("dialog", { name: "Withdraw this document?" });
  await withdraw.getByRole("textbox").fill("Replaced by the brand guide.");
  await withdraw.getByRole("button", { name: "Withdraw" }).click();
  await row.getByText("Withdrawn").waitFor();
  assert.equal(await row.getByRole("button", { name: /Withdraw/ }).count(), 0);
  const sources = (await api(`/api/brands/${brand.id}/sources`)).body;
  assert.equal(sources.find((s) => s.title === "Fact sheet").status, "archived");

  // A brand rule: added on the page, saved, and it catches a word in a new draft.
  await go(p, "/app/rules");
  await p.getByLabel("Word or phrase").fill("guaranteed");
  await p.getByRole("button", { name: /Add to the rules below/ }).click();
  await p.getByRole("button", { name: "Save rules" }).click();
  await says(p, /Saved as version 1/);
  assert.ok((await api(`/api/brands/${brand.id}/rules`)).body.rules.prohibited_terms.length === 1, "saved on the server");

  const id = await checkDraft(p, "The Lumen Pods are guaranteed to last.", "E2E rule draft");
  const review = (await api(`/api/reviews/${id}`)).body;
  assert.ok(review.findings.some((f) => f.check_type === "rule" && f.rule_type === "prohibited_term"), "the rule fired");
  await p.getByRole("region", { name: "Problems found" }).getByText(/guaranteed/).first().waitFor();
  await p.getByRole("heading", { name: "Brand rule checks" }).waitFor();

  // The editor's re-check: a new review of the same version.
  await go(p, `/app/review-edit?id=${id}`);
  await p.getByRole("button", { name: /Check again/ }).first().click();
  await p.waitForURL((u) => u.searchParams.get("id") && u.searchParams.get("id") !== id, { timeout: 90000 });
  await p.waitForLoadState("networkidle");

  // Coverage opens for that draft, and is honest about a placeholder check.
  await go(p, `/app/coverage?id=${id}`);
  await main(p).getByRole("heading", { name: "Coverage" }).waitFor();

  // Removing the rules.
  await go(p, "/app/rules");
  await p.getByRole("button", { name: "Remove all rules" }).click();
  await p.getByRole("dialog").getByRole("button", { name: "Remove rules" }).click();
  await p.waitForLoadState("networkidle");
  assert.equal((await api(`/api/brands/${brand.id}/rules`)).body.rules, null);
}
