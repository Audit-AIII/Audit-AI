import type { ReactNode } from "react";
import { Heading } from "@/components/primitives/Heading";
import { SpecTable } from "@/components/primitives/SpecTable";
import { Shore, type ShellSpot } from "@/components/layout/Shore";

type Status = "contradicted" | "unverified" | "supported" | "withdrawn";

const STATUS: Record<Status, { glyph: string; label: string }> = {
  supported: { glyph: "✓", label: "Matches" },
  unverified: { glyph: "?", label: "Not proven yet" },
  contradicted: { glyph: "≠", label: "Doesn’t match" },
  withdrawn: { glyph: "↻", label: "Rule changed" },
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
    source: "Approved facts, v3",
    excerpt: "Battery life: 12 hours",
    title: "“Lasts 24 hours”",
    copy: "A product page promised a full day. Your approved facts say 12 hours, so Audit AI shows both numbers side by side.",
    spec: { check: "Facts", source: "Approved facts, v3", result: "Doesn’t match (approved: 12 hours)" },
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
    source: "Your approved documents",
    excerpt: "No approved document ranks the product “number one”.",
    title: "“India’s number-one eco-friendly solution”",
    copy: "Nothing you have approved backs up “number one”. Audit AI suggests softer wording, and you decide.",
    spec: { check: "Claims", source: "Your approved documents", result: "Not proven yet: needs softer wording" },
    snippet: {
      channel: "Social post",
      body: (
        <>
          Meet <mark className="snip__mark snip__mark--unverified">India’s number-one eco-friendly solution</mark> for
          everyday cleaning.
        </>
      ),
      chips: <Chip status="unverified" />,
    },
  },
  {
    label: "Tone · coming next",
    window: "rect",
    source: "Readability and tone rules",
    excerpt: "Write buttons in normal case. One exclamation mark at most.",
    title: "“BUY NOW!!!”",
    copy: "Tone is coming next, not built yet: this is how it will look. All capitals are harder to read for many people, and shouting does not fit the brand’s voice.",
    spec: { check: "Tone (coming next)", source: "Readability and tone rules", result: "Two problems" },
    snippet: {
      channel: "Email",
      body: (
        <>
          <mark className="snip__mark snip__mark--contradicted">BUY NOW!!!</mark> The spring offer ends on Friday.
        </>
      ),
      chips: (
        <>
          <Chip status="contradicted">Hard to read</Chip>
          <Chip status="contradicted">Off-brand tone</Chip>
        </>
      ),
    },
  },
  {
    label: "Source Watch",
    window: "circle",
    source: "Brand Guide v4",
    excerpt: "Guide changed · 3 pieces sent back",
    title: "Brand guide updated",
    copy: "When the brand guide changed, Source Watch sent three already-approved pieces back for review, so nothing stays live on old rules.",
    spec: { check: "Source Watch", source: "Brand guide, v4", result: "3 approved pieces sent back for review" },
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
        <span className="t-caption">Based on</span>
        <span>{f.source}</span>
      </div>
    </figure>
  );
}

/** Sample findings in alternating sleeve · snippet · text rows. */
// Beach decor in the open sand around the heading (hidden below 900px).
const SHELLS: ShellSpot[] = [
  { kind: "star", x: "80%", y: "60px", size: 120, rotate: 16 },
  { kind: "cockle", x: "60%", y: "150px", size: 71, rotate: -22 },
  { kind: "pebble", x: "70%", y: "96px", size: 20 },
  { kind: "tide", x: "40%", y: "0px", size: 560 },
  { kind: "pearls", x: "56%", y: "90px", size: 48 },
  { kind: "glass", x: "68%", y: "205px", size: 39, rotate: -30, tone: "slate" },
  { kind: "pebble", x: "92%", y: "190px", size: 30, rotate: 15, tone: "rose" },
  { kind: "pebble", x: "74%", y: "150px", size: 27, tone: "ochre" },
];

export function Findings() {
  return (
    <section id="findings" className="section findings" aria-labelledby="findings-title">
      <Shore shells={SHELLS} />
      <div className="container">
        <div className="head-grid findings__head">
          <Heading id="findings-title" className="findings__title" data-r="up">
            Problems we have caught
          </Heading>
          <p className="t-lead findings__intro" data-r="up">
            <span className="findings__badge t-caption">Sample data</span>
            Four made-up examples that show what Audit AI flags, which document it checked against, and what
            happened next.
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
                    { label: "Based on", value: f.spec.source },
                    { label: "Outcome", value: f.spec.result },
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
