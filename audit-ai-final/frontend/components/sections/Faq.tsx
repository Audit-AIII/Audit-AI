import { Disclosure } from "@/components/primitives/Disclosure";
import { Heading } from "@/components/primitives/Heading";
import { Shore, type ShellSpot } from "@/components/layout/Shore";

// COPY TO REVIEW: §15 lists the questions only; answers follow DESIGN.md §0 and §15–§17.
const FAQ = [
  {
    id: "faq-rewrite",
    q: "Does Audit AI rewrite my content?",
    a: "No. It suggests changes and never touches the parts you lock, such as prices, dates and product names. Nothing changes until a person accepts it.",
  },
  {
    id: "faq-data",
    q: "Where does my data go?",
    a: "Your drafts and documents stay in your workspace. Each review comes with a Data Passport: a simple list of every AI service that read your text, and whether personal details were hidden first.",
  },
  {
    id: "faq-evidence",
    q: "What if there is no proof?",
    a: "The line is marked “not proven yet”, never “wrong”. A reviewer decides whether to add proof, soften the wording or remove it.",
  },
  {
    id: "faq-confidential",
    q: "How are private files handled?",
    a: "Files you mark as private are only read on your own server. They are never sent to an outside AI service.",
  },
  {
    id: "faq-legal",
    q: "Is this legal advice?",
    a: "No. The built-in advertising rules help reviewers spot risks. Your legal team still makes the final call.",
  },
];

// Beach decor in the open sand around the heading (hidden below 900px).
const SHELLS: ShellSpot[] = [
  { kind: "cockle", x: "9%", y: "300px", size: 110, rotate: 12 },
  { kind: "spiral", x: "25%", y: "420px", size: 76, rotate: -40 },
  { kind: "scallop", x: "12%", y: "540px", size: 80, rotate: 24 },
  { kind: "pebble", x: "28%", y: "330px", size: 22 },
  { kind: "tide", x: "-4%", y: "630px", size: 460 },
  { kind: "pearls", x: "20%", y: "360px", size: 48 },
  { kind: "glass", x: "33%", y: "490px", size: 33, rotate: -10, tone: "sea" },
  { kind: "pebble", x: "30%", y: "560px", size: 30, rotate: 25, tone: "ochre" },
  { kind: "pebble", x: "6%", y: "450px", size: 27, tone: "slate" },
  { kind: "pebble", x: "22%", y: "650px", size: 24, rotate: -20, tone: "rose" },
];

export function Faq() {
  return (
    <section id="faq" className="section faq" aria-labelledby="faq-title">
      <Shore shells={SHELLS} />
      <div className="container faq__grid">
        <div className="faq__head" data-r="up">
          <Heading id="faq-title" className="faq__title">
            Before you ask
          </Heading>
        </div>
        <div className="faq__list" data-r="up">
          {FAQ.map((f) => (
            <Disclosure key={f.id} id={f.id} question={f.q}>
              <p>{f.a}</p>
            </Disclosure>
          ))}
        </div>
      </div>
    </section>
  );
}
