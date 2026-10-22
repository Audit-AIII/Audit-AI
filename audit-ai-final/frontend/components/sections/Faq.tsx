import { Disclosure } from "@/components/primitives/Disclosure";
import { Heading } from "@/components/primitives/Heading";

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

export function Faq() {
  return (
    <section id="faq" className="section faq" aria-labelledby="faq-title">
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
