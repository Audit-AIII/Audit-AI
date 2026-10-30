// Brand voice findings. Skipped until the API sends them: nothing is ever faked here.
// When it fails to skip, replace this with a real journey; qa/tone-findings.mjs shows what to check.
import { reviewsOf } from "./lib.mjs";

export default async function journey(run) {
  const reviews = await reviewsOf(run.shared.asha);
  if (!reviews.some((r) => r.findings.some((f) => f.check_type === "tone"))) {
    const skip = new Error("the API sends no tone findings; no tone checker exists yet");
    skip.name = "Skip";
    throw skip;
  }
  throw new Error("The API now sends tone findings: write this journey against the real fields.");
}
