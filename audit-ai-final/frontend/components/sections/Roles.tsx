import { Heading } from "@/components/primitives/Heading";
import { TextLink } from "@/components/primitives/TextLink";
import { StartReviewButton } from "@/components/layout/StartReview";

// Single-user accounts (DECISIONS.md, decision 1): the owner writes, checks and decides.
const ROLES = [
  { name: "You approve", does: "Nothing is approved for you. Approve, send back or reject is always your click.", gets: "Your call", caption: "Decides" },
  { name: "Every decision is saved", does: "Who decided, when, and which version of the draft.", gets: "Full record", caption: "Saved" },
  { name: "Your documents stay yours", does: "One private account per user. Nobody else sees your brands or drafts.", gets: "Private", caption: "Yours" },
  { name: "Teams", does: "Planned: inviting others into an account.", gets: "Planned", caption: "Not yet" },
];

const PATH = ["Draft", "Checked", "Your decision", "Approved"];

/** Roles replace pricing tiers: an approval-path card beside the role rows. */
export function Roles() {
  return (
    <section className="section roles" aria-labelledby="roles-title">
      <div className="container roles__grid">
        <div className="roles__lid card" data-r="scale">
          <ol className="roles__path" aria-label="Approval path">
            {PATH.map((step, i) => (
              <li key={step} className={`roles__step${i === PATH.length - 1 ? " roles__step--end" : ""}`}>
                {i === PATH.length - 1 ? (
                  <span className="roles__dot" data-seal-target aria-hidden="true">
                    <span className="roles__tick">✓</span>
                  </span>
                ) : (
                  <span className="roles__dot" aria-hidden="true" />
                )}
                <span className="t-caption">{step}</span>
              </li>
            ))}
          </ol>
        </div>

        <div className="roles__sheet card" data-r="scale">
          <Heading id="roles-title" className="roles__title">
            You decide
          </Heading>
          <ul className="roles__list">
            {ROLES.map((r) => (
              <li key={r.name} className="roles__row">
                <h3 className="t-title roles__name">{r.name}</h3>
                <p className="t-body roles__does">{r.does}</p>
                <p className="roles__gets">
                  <span className="roles__gets-value relief-pressed">{r.gets}</span>
                  <span className="t-caption">{r.caption}</span>
                </p>
              </li>
            ))}
          </ul>
          <div className="roles__actions">
            <StartReviewButton />
            <TextLink href="#findings" arrow>
              See an example
            </TextLink>
          </div>
        </div>
      </div>
    </section>
  );
}
