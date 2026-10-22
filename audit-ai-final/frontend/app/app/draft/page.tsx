import { Button } from "@/components/primitives/Button";
import { Dropzone, Option, Panel, Panels, StageHead } from "@/components/app/Stage";

const SAMPLE =
  "Meet the new Aero earbuds. One charge lasts 24 hours, so you can leave the cable at home. India's number-one eco-friendly sound. BUY NOW!!!";

const PLACES = ["Website", "Social media post", "Email", "Product page", "Advert"];

export default function DraftStage() {
  return (
    <>
      <StageHead title="Draft" status="Not checked yet" />
      <Panels>
        <Panel n="01" label="Your text" title="Paste your draft">
          <label className="field">
            <span className="field__label">Text to check</span>
            <textarea className="field__input draft__text" defaultValue={SAMPLE} placeholder="Paste or type your text here" />
          </label>
          <Dropzone small title="Or add a file" hint="Word, PDF or image" />
        </Panel>

        <Panel n="02" label="Where it goes" title="Where will this be posted?">
          <div className="options" role="radiogroup" aria-label="Where will this be posted?">
            {PLACES.map((c, i) => (
              <Option key={c} type="radio" name="place" label={c} defaultChecked={i === 3} />
            ))}
          </div>
          <p className="t-body panel__note">
            Each place has its own rules. For example, adverts have stricter rules on promises.
          </p>
        </Panel>

        <Panel n="03" label="Privacy" title="Keep it private?">
          <Option
            label="Keep this draft private"
            help="It is checked inside your company only and never sent to an outside AI."
          />
          <p className="t-body panel__note">
            After the check, the Data Passport shows every tool that read your text.
          </p>
          <Button href="/app/review">Check my draft →</Button>
        </Panel>
      </Panels>
    </>
  );
}
