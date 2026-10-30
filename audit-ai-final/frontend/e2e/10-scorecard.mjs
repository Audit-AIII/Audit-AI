// Trust Scorecard: no stored run shows the published benchmark; a stored run equals the API; no provider gives its 409.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { apiAs, go, main, pageAs, registerApi, uniqueEmail } from "./lib.mjs";

export default async function journey(run) {
  // A new workspace has no stored run.
  const me = await registerApi(uniqueEmail("score"), "Sam Score");
  const p = await pageAs(run, me);
  await go(p, "/app/scorecard");
  const latest = await apiAs(me)("/api/evaluations/latest");

  if (latest.status === 404) {
    // The published file is the engine's own report, and the page says what it is.
    const published = JSON.parse(readFileSync("public/published-evaluation.json", "utf8"));
    const text = main(p);
    await text.getByText(published.report_id).first().waitFor();
    await text.getByText(/replayed recording/i).first().waitFor();
  } else {
    // A stored run (a shared database may hold one): the page shows the API's own values.
    assert.equal(latest.status, 200);
    const text = await main(p).innerText();
    assert.ok(text.includes(latest.body.dataset_version));
    assert.ok(text.includes(latest.body.id));
  }

  // No provider: the message, not a blank page. e2e/run.mjs has confirmed this server has none.
  await p.getByRole("button", { name: "Run evaluation" }).first().click();
  await p.getByRole("dialog").getByRole("button", { name: "Run evaluation" }).click();
  const alert = p.getByRole("alert").filter({ hasText: "The evaluation did not run." });
  await alert.waitFor({ timeout: 30000 });
  assert.match(await alert.innerText(), /provider/i);
  await p.getByRole("button", { name: "Retry" }).waitFor();
}
