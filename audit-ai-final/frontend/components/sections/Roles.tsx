import { Button } from "@/components/primitives/Button";
import { Heading } from "@/components/primitives/Heading";
import { TextLink } from "@/components/primitives/TextLink";

const ROLES = [
  { name: "Creator", does: "Submits drafts and fixes what is flagged.", gets: "Every draft", caption: "Submits" },
  { name: "Manager", does: "Signs off clean items in one click.", gets: "Clean", caption: "Signs off" },
  { name: "Reviewer", does: "Decides the high-risk findings.", gets: "High risk", caption: "Decides" },
];

const PATH = ["Draft", "Checked", "In review", "Approved"];

/** Roles replace pricing tiers: an approval-path card beside the role rows. */
export function Roles() {
  return (
    <section className="section roles" aria-labelledby="roles-title">
      <div className="container roles__grid">
        <div className="roles__lid card" data-r="scale">
          <ol className="roles__path" aria-label="Approval path">
            {PATH.map((step, i) => (
              <li key={step} className={`roles__step${i === PATH.length - 1 ? " roles__step--end" : ""}`}>
                <span className="roles__dot" aria-hidden="true" />
                <span className="t-caption">{step}</span>
              </li>
            ))}
          </ol>
          <p className="t-caption roles__fork">High risk → Reviewer · Clean → Manager</p>
        </div>

        <div className="roles__sheet card" data-r="scale">
          <Heading id="roles-title" className="roles__title">
            Three roles, one workflow
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
            <Button href="#contact">Start a review</Button>
            <TextLink href="#findings" arrow>
              See a sample finding
            </TextLink>
          </div>
        </div>
      </div>
    </section>
  );
}
