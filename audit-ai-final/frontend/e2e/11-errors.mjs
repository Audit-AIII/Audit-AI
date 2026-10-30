// A network failure explains itself and recovers. This is the one journey that blocks the API.
import { API, checkedOpenReview, go, main, pageAs, reviewsOf, WEB } from "./lib.mjs";

export default async function journey(run) {
  const { asha } = run.shared;
  const reviews = await reviewsOf(asha);
  const target = checkedOpenReview(reviews);
  const p = await pageAs(run, asha);

  let blocked = true;
  await p.route(`${API}/api/reviews/${target.id}`, (r) => (blocked ? r.abort() : r.continue()));
  await p.goto(`${WEB}/app/review?id=${target.id}`);
  await main(p).getByText(/Can’t reach the server/i).waitFor();
  blocked = false;
  await p.getByRole("button", { name: "Try again" }).click();
  await p.getByRole("region", { name: "What the checker found" }).waitFor();

  // A review with no findings, if the seed has one; qa/review-states.mjs forces it either way.
  const empty = reviews.find((r) => r.status === "completed" && r.findings.length === 0);
  if (empty) {
    await go(p, `/app/review?id=${empty.id}`);
    await main(p).getByText(/No problems were flagged/i).waitFor();
  }
}
