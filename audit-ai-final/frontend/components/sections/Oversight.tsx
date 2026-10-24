import { Heading } from "@/components/primitives/Heading";

const PASSPORT = [
  { step: "Claim check", service: "Outside AI service", note: "Only if one is set up" },
  { step: "Private document", service: "Local AI only", note: "Never sent out" },
];

/** Dark inset panel: who decides, the core principle, and the Data Passport. */
export function Oversight() {
  return (
    <section className="oversight" aria-labelledby="oversight-title">
      <div className="oversight__panel">
        <div className="oversight__grid">
          <Heading id="oversight-title" relief="raised" className="oversight__title" data-r="up">
            You stay in charge
          </Heading>
          <p className="t-lead oversight__intro" data-r="up">
            Audit AI only suggests. You approve it, send it back with a note, or reject it.
          </p>

          <figure className="oversight__quote" data-r="up">
            <blockquote className="oversight__statement">No proof means “not proven yet”, never “wrong”.</blockquote>
            <figcaption className="t-caption oversight__cite">Audit AI design principle</figcaption>
          </figure>

          <div className="oversight__window" data-r="scale">
            <article className="passport card" aria-label="Data Passport, sample data">
              <header className="passport__head">
                <h3 className="t-title passport__title">Data Passport</h3>
                <span className="snip__sample t-caption">Sample data</span>
              </header>
              <p className="t-body passport__lead">Every AI service that read your text, listed in plain view.</p>
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
