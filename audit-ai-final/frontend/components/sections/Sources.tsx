import { Heading } from "@/components/primitives/Heading";

type Glyph = "liner" | "stack" | "fine" | "deep" | "comb";

const SOURCES: { name: string; usedFor: string; reads: string; glyph: Glyph }[] = [
  { name: "Brand guidelines", usedFor: "Tone, terms", reads: "PDF, DOCX", glyph: "liner" },
  { name: "Fact sheet", usedFor: "Numbers, dates", reads: "CSV", glyph: "stack" },
  { name: "Approved claims", usedFor: "Safe wording, expiry", reads: "Library", glyph: "fine" },
  { name: "Regulation packs", usedFor: "Claims law", reads: "India green claims first", glyph: "deep" },
  { name: "Approved assets", usedFor: "Palette, logos", reads: "PNG, SVG", glyph: "comb" },
];

/** Cross-section glyph: raised liner bars around a flute (wave) or honeycomb core, after DESIGN.md §6.13. */
function Section({ glyph }: { glyph: Glyph }) {
  return (
    <div className={`xsec xsec--${glyph}`} aria-hidden="true">
      <span className="xsec__bar" />
      {glyph === "stack" && <span className="xsec__bar" />}
      {(glyph === "fine" || glyph === "deep") && (
        <svg className="xsec__flute" viewBox="0 0 320 28" preserveAspectRatio="none">
          <path
            d={
              glyph === "fine"
                ? "M0 14 " + Array.from({ length: 16 }, (_, i) => `q 10 ${i % 2 ? 12 : -12} 20 0`).join(" ")
                : "M0 14 " + Array.from({ length: 9 }, (_, i) => `q 18 ${i % 2 ? 18 : -18} 36 0`).join(" ")
            }
          />
        </svg>
      )}
      {glyph === "comb" && (
        <span className="xsec__comb">
          {Array.from({ length: 14 }, (_, i) => (
            <i key={i} />
          ))}
        </span>
      )}
      <span className="xsec__bar" />
    </div>
  );
}

export function Sources() {
  return (
    <section id="sources" className="section sources" aria-labelledby="sources-title">
      <div className="container">
        <div className="sources__head">
          <Heading id="sources-title" className="sources__title" data-r="up">
            Five sources we read
          </Heading>
          {/* TODO: replace with a warm-graded photo of real source documents (webp, lazy, alt text). */}
          <div className="sources__photo placeholder" role="img" aria-label="Placeholder for a photo of source documents" data-r="scale">
            <span className="t-caption">Photo — TODO</span>
          </div>
        </div>

        <ul className="sources__list">
          {SOURCES.map((s) => (
            <li key={s.name} className="sources__row" data-r="up">
              <Section glyph={s.glyph} />
              <div className="sources__name">
                <h3 className="t-title">{s.name}</h3>
              </div>
              <dl className="sources__meta">
                <div>
                  <dt className="t-caption">Used for</dt>
                  <dd>{s.usedFor}</dd>
                </div>
                <div>
                  <dt className="t-caption">Reads</dt>
                  <dd>{s.reads}</dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>

        <div className="sources__punch">
          <div className="sources__punch-text" data-r="up">
            <h3 className="t-title">Confidential stays local.</h3>
            <p className="t-body">Sources marked confidential never go to an external model.</p>
          </div>
          <div className="disc" data-r="scale" aria-hidden="true">
            <span className="disc__hole" />
          </div>
        </div>
      </div>
    </section>
  );
}
