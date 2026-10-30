// Shared helpers for the end-to-end journeys. See e2e/README.md.
import assert from "node:assert/strict";

export const WEB = "http://localhost:3000";
export const API = "http://localhost:8000";
export const password = process.env.AUDIT_PASSWORD;
if (!password) throw new Error("Set AUDIT_PASSWORD to the seed's DEMO_PASSWORD. See e2e/README.md.");

let serial = 0;
export const uniqueEmail = (tag) => `e2e-${tag}-${Date.now()}-${++serial}@example.com`;

/** Calls the real API as this person. Answers { status, body } and never throws on a refusal. */
export function apiAs(login) {
  return async (path, { method = "GET", body, headers = {} } = {}) => {
    const res = await fetch(`${API}${path}`, {
      method,
      headers: {
        ...(login ? { Authorization: `Bearer ${login.access_token}` } : {}),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let parsed = null;
    try {
      parsed = await res.json();
    } catch {
      /* no body */
    }
    return { status: res.status, body: parsed };
  };
}

export async function signInApi(email) {
  const { status, body } = await apiAs(null)("/api/auth/login", { method: "POST", body: { email, password } });
  assert.equal(status, 200, `sign in ${email}`);
  return body;
}

export async function registerApi(email, name) {
  const { status, body } = await apiAs(null)("/api/auth/register", { method: "POST", body: { email, password, display_name: name, brand_name: `${name} brand` } });
  assert.equal(status, 201, `register ${email}: ${JSON.stringify(body)}`);
  return body;
}

/** Joins through the API, for people a journey only needs in the background. Answers their team session. */
export async function joinApi(owner, role, name) {
  const email = uniqueEmail(role);
  const invite = await apiAs(owner)("/api/workspace/invitations", { method: "POST", body: { email, role } });
  assert.equal(invite.status, 201, JSON.stringify(invite.body));
  const person = await registerApi(email, name);
  const accepted = await apiAs(person)("/api/invitations/accept", { method: "POST", body: { token: invite.body.token } });
  assert.equal(accepted.status, 200, JSON.stringify(accepted.body));
  return { ...accepted.body, email };
}

/** Gives a brand one approved document, so a draft can be checked against it. */
export async function addApprovedDocument(login, brandId) {
  const form = new FormData();
  form.append("file", new Blob(["The Lumen Pods last 24 hours on one charge."], { type: "text/plain" }), "spec.txt");
  form.append("title", "Spec");
  form.append("sensitivity", "normal");
  form.append("approve", "true");
  const res = await fetch(`${API}/api/brands/${brandId}/sources`, { method: "POST", headers: { Authorization: `Bearer ${login.access_token}` }, body: form });
  assert.equal(res.status, 201, await res.text());
}

export const sessionOf = (l) => ({
  email: l.user.email,
  name: l.user.display_name ?? undefined,
  token: l.access_token,
  userId: l.user.id,
  organisation: l.organisation,
  role: l.role,
  workspace: l.workspace,
});

/** A page signed in as this person. Registered with the run, so failures get a screenshot. */
export async function pageAs(run, login, { width = 1182, height = 937 } = {}) {
  const ctx = await run.browser.newContext({ viewport: { width, height } });
  if (login) {
    const page = await ctx.newPage();
    await page.goto(`${WEB}/login`);
    await page.evaluate((s) => localStorage.setItem("audit-ai.session", s), JSON.stringify(sessionOf(login)));
    await page.close();
  }
  const p = await ctx.newPage();
  p.on("pageerror", (e) => run.pageErrors.push(`${p.url()}: ${e.message}`));
  run.open.push(p);
  return p;
}

/** Waits for the page's own requests to finish; no fixed sleeps. */
export async function go(p, path) {
  await p.goto(`${WEB}${path}`);
  await p.waitForLoadState("networkidle");
}

export const main = (p) => p.getByRole("main").first();
export const says = (p, text) => main(p).getByText(text).first().waitFor();
export const noSidewaysScroll = (p) => p.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
export const check = async (p, name) => p.getByRole("button", { name, exact: true }).click();

/** Buttons drawn in the decision panel. */
export const decisionButtons = async (p) => {
  const panel = p.getByRole("region", { name: "Your decision" });
  await panel.waitFor();
  return (await panel.getByRole("button").allInnerTexts()).map((s) => s.trim());
};

/** Checks a draft through the page. Answers the new review's id. */
export async function checkDraft(p, text, title) {
  await go(p, "/app/draft");
  await p.getByLabel("Text to check").fill(text);
  await p.getByLabel("Title (optional)").fill(title);
  const submit = p.getByRole("button", { name: /Check my draft/ });
  await assert.doesNotReject(submit.waitFor());
  await p.waitForFunction(() => !document.querySelector('button[type="submit"]')?.disabled);
  await submit.click();
  await p.waitForURL("**/app/review?id=*", { timeout: 90000 });
  await p.waitForLoadState("networkidle");
  return new URL(p.url()).searchParams.get("id");
}

export const reviewsOf = async (login) => (await apiAs(login)("/api/reviews?limit=100")).body;

/** A review the seed really checked and nobody has decided. New drafts here are placeholders: no AI provider. */
export const checkedOpenReview = (reviews) =>
  reviews.find((r) => r.status === "needs_human_review" && r.is_current_version && !/^stub/i.test(r.engine?.provider ?? "") && r.findings.some((f) => f.verification_status !== "supported"));
