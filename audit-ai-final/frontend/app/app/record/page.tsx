import { Panel, Panels, StageHead } from "@/components/app/Stage";

const TIMELINE = [
  { at: "10:02", who: "Writer", what: "Sent the draft “Aero earbuds launch”" },
  { at: "10:02", who: "Audit AI", what: "Checked the draft and found 4 problems" },
  { at: "10:09", who: "Writer", what: "Used the suggested battery change (12 hours)" },
  { at: "10:11", who: "Writer", what: "Asked a reviewer about the eco-friendly claim" },
  { at: "10:30", who: "Reviewer", what: "Toned down the claim and approved it" },
];

const PASSPORT = [
  { step: "Tone check", service: "Outside AI service", note: "Names removed first" },
  { step: "Fact check", service: "Inside your company", note: "Never left" },
  { step: "Brand guide (private)", service: "Inside your company", note: "Never left" },
];

export default function RecordStage() {
  return (
    <>
      <StageHead title="Record" status="Approved" />
      <Panels>
        <Panel n="01" label="What happened" title="Timeline">
          <ol className="timeline">
            {TIMELINE.map((t, i) => (
              <li key={i} className="timeline__item">
                <span className="timeline__at t-caption">{t.at}</span>
                <div>
                  <p className="rows__title">{t.who}</p>
                  <p className="rows__meta">{t.what}</p>
                </div>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel n="02" label="Data Passport" title="Who read your text">
          <ul className="rows">
            {PASSPORT.map((r) => (
              <li key={r.step} className="rows__item">
                <div>
                  <p className="rows__title">{r.step}</p>
                  <p className="rows__meta">{r.service}</p>
                </div>
                <span className="tag">{r.note}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel n="03" label="Share it" title="Download">
          <p className="t-body panel__note">One PDF with your draft, each problem, why it was flagged and what was decided.</p>
          <button type="button" className="decision" disabled>
            Download as PDF · coming soon
          </button>
        </Panel>
      </Panels>
    </>
  );
}
