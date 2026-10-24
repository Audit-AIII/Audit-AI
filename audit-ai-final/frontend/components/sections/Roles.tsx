import { Heading } from "@/components/primitives/Heading";
import { TextLink } from "@/components/primitives/TextLink";
import { StartReviewButton } from "@/components/layout/StartReview";

// Today every account is one person who writes, checks and decides. Separate team roles are planned.
const ROLES = [
  { name: "Writer", does: "Sends drafts in and fixes what is flagged.", gets: "Every draft", caption: "Sends in" },
  { name: "Decider", does: "Reads why each line was flagged, then approves, sends back or rejects.", gets: "Checked drafts", caption: "Decides" },
  { name: "Team roles", does: "Planned: separate reviewers and managers, with risky drafts routed to a reviewer.", gets: "Planned", caption: "Not yet" },
];

const PATH = ["Draft", "Checked", "Being reviewed", "Approved"];

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
          <p className="t-caption roles__fork">Planned: Risky → Reviewer · Clean → Manager</p>
        </div>

        <div className="roles__sheet card" data-r="scale">
          <Heading id="roles-title" className="roles__title">
            A person makes every call
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
