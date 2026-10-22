import { Heading } from "@/components/primitives/Heading";

const PASSPORT = [
  { step: "Tone check", service: "LLM API", note: "Redacted" },
  { step: "Fact check", service: "Local retrieval", note: "No external call" },
  { step: "Confidential source", service: "Local model", note: "Local only" },
];

/** Dark inset panel: who decides, the core principle, and the Data Passport. */
export function Oversight() {
  return (
    <section className="oversight" aria-labelledby="oversight-title">
      <div className="oversight__panel">
        <div className="oversight__grid">
          <Heading id="oversight-title" relief="raised" className="oversight__title" data-r="up">
            People stay in charge
          </Heading>
          <p className="t-lead oversight__intro" data-r="up">
            Audit AI proposes. Reviewers accept, edit, dismiss or escalate.
          </p>

          <figure className="oversight__quote" data-r="up">
            <blockquote className="oversight__statement">Missing evidence means unverified, never false.</blockquote>
            <figcaption className="t-caption oversight__cite">Audit AI design principle</figcaption>
          </figure>

          <div className="oversight__window" data-r="scale">
            <article className="passport card" aria-label="Data Passport, sample data">
              <header className="passport__head">
                <h3 className="t-title passport__title">Data Passport</h3>
                <span className="snip__sample t-caption">Sample data</span>
              </header>
              <ul className="passport__rows">
                {PASSPORT.map((r) => (
                  <li key={r.step} className="passport__row">
                    <span className="passport__step">{r.step}</span>
                    <span className="passport__service">{r.service}</span>
                    <span className="t-caption passport__note">{r.note}</span>
                  </li>
                ))}
              </ul>
            </article>
          </div>
        </div>
      </div>
    </section>
  );
}
