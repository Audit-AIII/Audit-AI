import type { ReactNode } from "react";
import { Heading } from "@/components/primitives/Heading";
import { SpecTable } from "@/components/primitives/SpecTable";

type Status = "contradicted" | "unverified" | "supported" | "withdrawn";

const STATUS: Record<Status, { glyph: string; label: string }> = {
  supported: { glyph: "✓", label: "Supported" },
  unverified: { glyph: "?", label: "Unverified" },
  contradicted: { glyph: "≠", label: "Contradicted" },
  withdrawn: { glyph: "↻", label: "Source withdrawn" },
};

function Chip({ status, children }: { status: Status; children?: ReactNode }) {
  const s = STATUS[status];
  return (
    <span className={`chip chip--${status}`}>
      <span aria-hidden="true">{s.glyph}</span> {children ?? s.label}
    </span>
  );
}

type Finding = {
  label: string;
  window: "rect" | "circle";
  source: string;
  excerpt: string;
  title: string;
  copy: string;
  spec: { check: string; source: string; result: string };
  snippet: { channel: string; body: ReactNode; chips: ReactNode };
};

// Sample data (§15 row 5). COPY TO REVIEW: row descriptions and snippet sentences.
const FINDINGS: Finding[] = [
  {
    label: "Facts",
    window: "rect",
    source: "Fact sheet v3",
    excerpt: "Battery life: 12 hours",
    title: "“Lasts 24 hours”",
    copy: "A product page promised a full day. The approved fact sheet says twelve hours, so the finding shows both values side by side.",
    spec: { check: "Facts", source: "Fact sheet v3", result: "Contradicted (approved: 12 hours)" },
    snippet: {
      channel: "Product page",
      body: (
        <>
          One charge <mark className="snip__mark snip__mark--contradicted">lasts 24 hours</mark>, so you can leave the
          cable at home.
        </>
      ),
      chips: <Chip status="contradicted" />,
    },
  },
  {
    label: "Claims",
    window: "circle",
    source: "Green-claims pack",
    excerpt: "Superlatives need dated, independent proof.",
    title: "“India’s number-one eco-friendly solution”",
    copy: "No approved evidence backs the superlative. Audit AI suggests a qualified version and leaves the choice to the reviewer.",
    spec: { check: "Claims", source: "Green-claims pack", result: "Unsupported — qualifier needed" },
    snippet: {
      channel: "Social post",
      body: (
        <>
          Meet <mark className="snip__mark snip__mark--unverified">India’s number-one eco-friendly solution</mark> for
          everyday cleaning.
        </>
      ),
      chips: <Chip status="unverified">Unsupported</Chip>,
    },
  },
  {
    label: "Tone",
    window: "rect",
    source: "Accessibility + tone rules",
    excerpt: "Sentence case for calls to action. One exclamation mark at most.",
    title: "“BUY NOW!!!”",
    copy: "One line, two findings: all caps is harder to read for many people, and the shouting breaks the brand’s tone rules.",
    spec: { check: "Accessibility, tone", source: "Accessibility + tone rules", result: "Two findings" },
    snippet: {
      channel: "Email",
      body: (
        <>
          <mark className="snip__mark snip__mark--contradicted">BUY NOW!!!</mark> The spring offer ends on Friday.
        </>
      ),
      chips: (
        <>
          <Chip status="contradicted">Accessibility</Chip>
          <Chip status="contradicted">Tone</Chip>
        </>
      ),
    },
  },
  {
    label: "Source Watch",
    window: "circle",
    source: "Brand Guide v4",
    excerpt: "v3 → v4 · 3 approved items re-flagged",
    title: "Brand Guide v4 uploaded",
    copy: "When the brand guide changed, three pieces that were already approved went back to review instead of staying live on old rules.",
    spec: { check: "Source Watch", source: "Brand Guide v4", result: "3 approved items re-flagged" },
    snippet: {
      channel: "Source Watch",
      body: (
        <span className="snip__rows">
          <span>Spring landing page</span>
          <span>Launch email</span>
          <span>Store banner</span>
        </span>
      ),
      chips: <Chip status="withdrawn" />,
    },
  },
];

function Sleeve({ f }: { f: Finding }) {
  return (
    <div className="finding__sleeve card" data-r="scale">
      <div className={`finding__window finding__window--${f.window}`}>
        <span className="finding__excerpt-source t-caption">{f.source}</span>
        <span className="finding__excerpt">{f.excerpt}</span>
      </div>
      <span className="finding__label t-title">{f.label}</span>
    </div>
  );
}

function Snippet({ f }: { f: Finding }) {
  return (
    <figure className="snip" data-r="scale" aria-label={`Sample review screen: ${f.title}`}>
      <div className="snip__bar">
        <span className="t-caption">Review · {f.snippet.channel}</span>
        <span className="snip__sample t-caption">Sample data</span>
      </div>
      <p className="snip__body">{f.snippet.body}</p>
      <div className="snip__chips">{f.snippet.chips}</div>
      <div className="snip__evidence">
        <span className="t-caption">Evidence</span>
        <span>{f.source}</span>
      </div>
    </figure>
  );
}

/** Sample findings in alternating sleeve · snippet · text rows. */
export function Findings() {
  return (
    <section id="findings" className="section findings" aria-labelledby="findings-title">
      <div className="container">
        <div className="head-grid findings__head">
          <Heading id="findings-title" className="findings__title" data-r="up">
            Findings we have caught
          </Heading>
          <p className="t-lead findings__intro" data-r="up">
            <span className="findings__badge t-caption">Sample data</span>
            Four examples, made up to show how a finding reads: what was flagged, which source decided it, and the
            result.
          </p>
        </div>
        <ol className="findings__list">
          {FINDINGS.map((f, i) => (
            <li key={f.label} className={`finding${i % 2 ? " finding--mirror" : ""}`}>
              <Sleeve f={f} />
              <Snippet f={f} />
              <div className="finding__text" data-r="up">
                <h3 className="t-title finding__title">{f.title}</h3>
                <p className="t-body finding__copy">{f.copy}</p>
                <SpecTable
                  rows={[
                    { label: "Check", value: f.spec.check },
                    { label: "Source", value: f.spec.source },
                    { label: "Result", value: f.spec.result },
                  ]}
                />
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
