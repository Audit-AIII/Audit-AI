import { Heading } from "@/components/primitives/Heading";

type Kind = "guide" | "facts" | "claims" | "rules" | "logos";

const SOURCES: { kind: Kind; name: string; checks: string; add: string }[] = [
  { kind: "guide", name: "Brand guide", checks: "Your voice and the words you use", add: "PDF or Word file" },
  { kind: "facts", name: "Key facts", checks: "Prices, numbers and dates", add: "Spreadsheet (CSV)" },
  { kind: "claims", name: "Approved claims", checks: "Promises you are allowed to make, and until when", add: "Added inside Audit AI" },
  { kind: "rules", name: "Advertising rules", checks: "What the law lets you claim", add: "Built in, starting with India’s eco-claim rules" },
  { kind: "logos", name: "Logos and colours", checks: "Brand colours and how the logo is used", add: "PNG or SVG images" },
];

/** A small paper drawing of each source, so the row shows what it is. */
function SourceVisual({ kind }: { kind: Kind }) {
  switch (kind) {
    case "guide":
      return (
        <div className="src src--guide">
          <span className="src-page">
            <b>Aa</b>
            <i />
            <i />
            <i />
          </span>
          <span className="src-page src-page--back" />
        </div>
      );
    case "facts":
      return (
        <div className="src src--facts">
          <span className="src-table">
            <span>Battery</span>
            <b>12 h</b>
            <span>Price</span>
            <b>₹2,499</b>
            <span>Launch</span>
            <b>1 Mar</b>
          </span>
        </div>
      );
    case "claims":
      return (
        <div className="src src--claims">
          <span className="src-claim">
            <span className="src-claim__tick">✓</span>
            <span>“Made with 30% recycled plastic”</span>
          </span>
          <span className="src-expiry">Valid until Dec 2026</span>
        </div>
      );
    case "rules":
      return (
        <div className="src src--rules">
          <span className="src-book">
            <b>§</b>
          </span>
          <span className="src-book src-book--2" />
          <span className="src-book src-book--3" />
        </div>
      );
    case "logos":
      return (
        <div className="src src--logos">
          <span className="src-logo">A.</span>
          <span className="src-swatches">
            <i style={{ background: "var(--canvas)" }} />
            <i style={{ background: "var(--ink-2)" }} />
            <i style={{ background: "var(--surface)" }} />
          </span>
        </div>
      );
  }
}

export function Sources() {
  return (
    <section id="sources" className="section sources" aria-labelledby="sources-title">
      <div className="container">
        <div className="sources__head">
          <Heading id="sources-title" className="sources__title" data-r="up">
            Five things we check against
          </Heading>
          <p className="t-lead sources__intro" data-r="up">
            You add these once. Every draft is then checked against them, and each flag tells you which one it came
            from.
          </p>
        </div>

        <ul className="sources__list">
          {SOURCES.map((s) => (
            <li key={s.kind} className="sources__row" data-r="up">
              <div aria-hidden="true">
                <SourceVisual kind={s.kind} />
              </div>
              <h3 className="t-title sources__name">{s.name}</h3>
              <dl className="sources__meta">
                <div>
                  <dt className="t-caption">Checks</dt>
                  <dd>{s.checks}</dd>
                </div>
                <div>
                  <dt className="t-caption">You add</dt>
                  <dd>{s.add}</dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>

        <div className="sources__punch">
          <div className="sources__punch-text" data-r="up">
            <h3 className="t-title">Private stays private.</h3>
            <p className="t-body">
              Documents you mark as private are only read on your own server. They are never sent to an outside AI.
            </p>
          </div>
          <div className="disc" data-r="scale" aria-hidden="true">
            <span className="disc__hole" data-seal-source />
          </div>
        </div>
      </div>
    </section>
  );
}
