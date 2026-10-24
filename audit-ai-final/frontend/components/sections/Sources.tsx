import { Heading } from "@/components/primitives/Heading";
import { BeachFind, Shore, type ShellSpot } from "@/components/layout/Shore";

type Kind = "guide" | "facts" | "claims" | "rules" | "logos";

// `soon`: shown as "Coming next". Today any approved PDF, Word or text document is checked against.
const SOURCES: { kind: Kind; name: string; checks: string; add: string; soon?: boolean }[] = [
  { kind: "guide", name: "Brand guide", checks: "Facts and promises written in it", add: "PDF, Word or text file" },
  { kind: "facts", name: "Key facts", checks: "Prices, numbers and dates", add: "PDF, Word or text file" },
  { kind: "claims", name: "Approved claims", checks: "Promises you are allowed to make, and until when", add: "Coming next", soon: true },
  { kind: "rules", name: "Advertising rules", checks: "What the law lets you claim", add: "Coming next", soon: true },
  { kind: "logos", name: "Logos and colours", checks: "Brand colours and how the logo is used", add: "Coming next", soon: true },
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

// Beach decor in the open sand around the heading (hidden below 900px).
const SHELLS: ShellSpot[] = [
  { kind: "dollar", x: "66%", y: "120px", size: 136, rotate: 8 },
  { kind: "auger", x: "84%", y: "220px", size: 97, rotate: 38 },
  { kind: "pebble", x: "81%", y: "112px", size: 24, rotate: 30 },
  { kind: "pebble", x: "60%", y: "290px", size: 16 },
  { kind: "conch", x: "56%", y: "250px", size: 82, rotate: 14 },
  { kind: "glass", x: "79%", y: "60px", size: 39, rotate: 35, tone: "sea" },
  { kind: "pearls", x: "90%", y: "330px", size: 45 },
  { kind: "pebble", x: "76%", y: "300px", size: 30, rotate: -15, tone: "charcoal" },
  { kind: "pebble", x: "92%", y: "110px", size: 33, rotate: 20, tone: "sage" },
  { kind: "pebble", x: "62%", y: "80px", size: 24, tone: "terracotta" },
];

// A small find lying in the sand beside each row's drawing (same order as SOURCES).
const FINDS: Parameters<typeof BeachFind>[0][][] = [
  [{ kind: "scallop", size: 40, rotate: 18 }, { kind: "pebble", tone: "sage", size: 20, rotate: -12 }],
  [{ kind: "pearls", size: 38 }],
  [{ kind: "glass", tone: "sea", size: 30, rotate: 30 }, { kind: "pebble", tone: "terracotta", size: 18 }],
  [{ kind: "spiral", size: 34, rotate: -20 }],
  [{ kind: "star", size: 40, rotate: 12 }, { kind: "pebble", tone: "slate", size: 18, rotate: 20 }],
];

export function Sources() {
  return (
    <section id="sources" className="section sources" aria-labelledby="sources-title">
      <Shore shells={SHELLS} />
      <div className="container">
        <div className="sources__head">
          <Heading id="sources-title" className="sources__title" data-r="up">
            What we check against
          </Heading>
          <p className="t-lead sources__intro" data-r="up">
            You add your approved documents once. Every draft is then checked against them, and each flag tells you
            which one it came from. Three more kinds of source are coming next.
          </p>
        </div>

        <ul className="sources__list">
          {SOURCES.map((s, i) => (
            <li key={s.kind} className="sources__row" data-r="up">
              <div className="sources__visual" aria-hidden="true">
                <SourceVisual kind={s.kind} />
                {FINDS[i]?.map((f, j) => (
                  <BeachFind key={j} {...f} className={`sources__find sources__find--${j ? "b" : "a"}`} />
                ))}
              </div>
              <h3 className="t-title sources__name">
                {s.name}
                {s.soon && <span className="checks__soon">Coming next</span>}
              </h3>
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
