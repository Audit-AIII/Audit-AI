import { Button } from "@/components/primitives/Button";
import { Panel, Panels, StageHead } from "@/components/app/Stage";

const PATH = [
  { step: "Checked", who: "By Audit AI", done: true },
  { step: "Fixed", who: "By the writer", done: true },
  { step: "Second look", who: "By a reviewer, for risky changes", done: false },
  { step: "Approved", who: "By a manager", done: false },
];

export default function DecideStage() {
  return (
    <>
      <StageHead title="Decide" status="Waiting for you" />
      <Panels>
        <Panel n="01" label="Suggested change" title="What would change">
          <p className="diff">
            <span className="lock">
              <svg className="lock__icon" viewBox="0 0 12 14" aria-hidden="true">
                <rect x="1" y="6" width="10" height="7.5" rx="1.5" />
                <path d="M3.5 6V4.2a2.5 2.5 0 0 1 5 0V6" />
              </svg>
              <span className="sr-only">Locked: </span>Aero earbuds
            </span>
            . One charge lasts <del>24 hours</del> <ins>12 hours</ins>, so you can leave the cable at home.
          </p>
          <div className="recheck" role="status">
            <span className="recheck__stamp">✓</span>
            <div>
              <p className="rows__title">Checked again: all 4 pass</p>
              <p className="rows__meta">The new sentence passes every check, and the words you locked stay as they are.</p>
            </div>
          </div>
        </Panel>

        <Panel n="02" label="Your decision" title="What should we do?">
          <p className="t-body panel__note">We never change your text on our own. Pick one:</p>
          <div className="decisions">
            <Button type="button">Use this change</Button>
            <button type="button" className="decision">
              I’ll edit it myself
            </button>
            <button type="button" className="decision">
              Reject
            </button>
            <button type="button" className="decision">
              Ask a manager
            </button>
          </div>
          <label className="field">
            <span className="field__label t-caption">Note (optional)</span>
            <input className="field__input" placeholder="Add a note for your team" />
          </label>
        </Panel>

        <Panel n="03" label="Who approves" title="Approval steps">
          <ol className="path">
            {PATH.map((p) => (
              <li key={p.step} className={`path__step${p.done ? " is-done" : ""}`}>
                <span className="path__dot" aria-hidden="true">
                  {p.done ? "✓" : ""}
                </span>
                <div>
                  <p className="rows__title">{p.step}</p>
                  <p className="rows__meta">{p.who}</p>
                </div>
              </li>
            ))}
          </ol>
          <Button href="/app/record">See the record →</Button>
        </Panel>
      </Panels>
    </>
  );
}
