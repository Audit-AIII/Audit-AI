import { Button } from "@/components/primitives/Button";
import { Dropzone, Option, Panel, Panels, StageHead } from "@/components/app/Stage";

const LIBRARY = [
  { name: "Brand guide", detail: "Version 4 · PDF", privacy: "Private" },
  { name: "Product facts", detail: "Version 3 · Spreadsheet", privacy: "Team only" },
  { name: "Approved claims", detail: "12 claims you can safely make", privacy: "Team only" },
  { name: "Advertising rules", detail: "India rules on green claims · Included", privacy: "Public" },
  { name: "Logos and colours", detail: "Version 2 · Image files", privacy: "Team only" },
];

const CHECKS = [
  { check: "Sounds like your brand", from: "Brand guide" },
  { check: "Uses the right words", from: "Brand guide" },
  { check: "Facts are correct", from: "Product facts" },
  { check: "Promises can be proven", from: "Approved claims, advertising rules" },
  { check: "Logos and colours", from: "Logos and colours" },
  { check: "Easy to read", from: "Included for you" },
];

export default function SourcesStage() {
  return (
    <>
      <StageHead title="Sources" status="5 documents saved" />
      <Panels>
        <Panel n="01" label="Add a document" title="Upload your rules">
          <p className="t-body panel__note">
            Add the documents your content must follow. You only need to do this once.
          </p>
          <Dropzone title="Drag a file here" hint="Brand guide, product facts or logo · PDF, Word, Excel or image" />
          <Option
            label="Keep this file private"
            help="It stays inside your company and is never sent to an outside AI."
            defaultChecked
          />
          <Button type="button">Save document</Button>
        </Panel>

        <Panel n="02" label="Your documents" title="Saved documents">
          <ul className="rows">
            {LIBRARY.map((d) => (
              <li key={d.name} className="rows__item">
                <div>
                  <p className="rows__title">{d.name}</p>
                  <p className="rows__meta">{d.detail}</p>
                </div>
                <span className={`tag${d.privacy === "Private" ? " tag--private" : ""}`}>{d.privacy}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel n="03" label="What we check" title="Checked against">
          <dl className="spec">
            <div className="spec__row spec__row--head">
              <dt className="t-caption">We check that…</dt>
              <dd className="t-caption">Using</dd>
            </div>
            {CHECKS.map((c) => (
              <div className="spec__row" key={c.check}>
                <dt>{c.check}</dt>
                <dd>{c.from}</dd>
              </div>
            ))}
          </dl>
          <Button href="/app/draft">Next: check a draft →</Button>
        </Panel>
      </Panels>
    </>
  );
}
