import { Button } from "@/components/primitives/Button";
import { Panel, Panels, StageHead } from "@/components/app/Stage";

const PROBLEMS = [
  { id: "p1", check: "Facts", title: "Battery life doesn't match", status: "bad", label: "≠ Doesn’t match", sev: "●●●", sevWord: "High" },
  { id: "p2", check: "Promises", title: "“Number-one eco-friendly” has no proof", status: "warn", label: "? Not proven yet", sev: "●●○", sevWord: "Medium" },
  { id: "p3", check: "Easy to read", title: "All capitals are hard to read", status: "bad", label: "≠ Doesn’t match", sev: "●○○", sevWord: "Low" },
  { id: "p4", check: "Tone", title: "Shouting doesn't fit your voice", status: "bad", label: "≠ Doesn’t match", sev: "●○○", sevWord: "Low" },
];

export default function ReviewStage() {
  return (
    <>
      <StageHead title="Review" status="4 problems found" />
      <div className="coverage" aria-label="How much of the draft is backed by your documents">
        <span className="t-caption">Backed by your documents</span>
        <span className="coverage__bar">
          <span className="coverage__ok" style={{ width: "58%" }} />
          <span className="coverage__warn" style={{ width: "17%" }} />
          <span className="coverage__bad" style={{ width: "25%" }} />
        </span>
        <span className="coverage__pct">58%</span>
      </div>
      <Panels>
        <Panel n="01" label="Your draft" title="Problems marked">
          <p className="heat">
            <span className="heat__ok">Meet the new Aero earbuds.</span>{" "}
            <mark className="heat__bad" tabIndex={0}>
              One charge lasts 24 hours,
            </mark>{" "}
            <span className="heat__ok">so you can leave the cable at home.</span>{" "}
            <mark className="heat__warn" tabIndex={0}>
              India’s number-one eco-friendly sound.
            </mark>{" "}
            <mark className="heat__bad" tabIndex={0}>
              BUY NOW!!!
            </mark>
          </p>
          <p className="legend t-caption">
            <span className="legend__ok">✓ Matches</span> <span className="legend__warn">? Not proven yet</span>{" "}
            <span className="legend__bad">≠ Doesn’t match</span>
          </p>
        </Panel>

        <Panel n="02" label="Problems found" title="4 to look at">
          <ul className="rows">
            {PROBLEMS.map((p, i) => (
              <li key={p.id} className={`rows__item problem${i === 0 ? " is-selected" : ""}`}>
                <div>
                  <p className="t-caption">{p.check}</p>
                  <p className="rows__title">{p.title}</p>
                  <p className="rows__meta">
                    <span className={`chip chip--${p.status === "bad" ? "contradicted" : "unverified"}`}>{p.label}</span>{" "}
                    <span className="sev" aria-label={`${p.sevWord} severity`}>
                      {p.sev} {p.sevWord}
                    </span>
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel n="03" label="Why it was flagged" title="Battery life doesn't match">
          <div className="evidence">
            <p className="t-caption evidence__src">From your product facts (version 3)</p>
            <p className="evidence__quote">“Battery life (single charge): 12 hours”</p>
            <dl className="evidence__compare">
              <div>
                <dt className="t-caption">Your facts say</dt>
                <dd>12 hours</dd>
              </div>
              <div className="evidence__found">
                <dt className="t-caption">Your draft says</dt>
                <dd>24 hours</dd>
              </div>
            </dl>
          </div>
          <p className="t-body panel__note">
            <b>The problem:</b> the draft promises twice the battery life your product facts allow.
          </p>
          <p className="t-body panel__note">
            <b>We suggest:</b> “One charge lasts 12 hours.”
          </p>
          <Button href="/app/decide">Choose what to do →</Button>
        </Panel>
      </Panels>
    </>
  );
}
