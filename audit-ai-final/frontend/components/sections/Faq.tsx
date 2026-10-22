import { Disclosure } from "@/components/primitives/Disclosure";
import { Heading } from "@/components/primitives/Heading";

// COPY TO REVIEW: §15 lists the questions only; answers follow DESIGN.md §0 and §15–§17.
const FAQ = [
  {
    id: "faq-rewrite",
    q: "Does Audit AI rewrite my content?",
    a: "No. It suggests edits and keeps the parts you lock, such as prices, dates and product names. Nothing changes until a person accepts it.",
  },
  {
    id: "faq-data",
    q: "Where does my data go?",
    a: "Drafts and sources stay in your workspace. Each review has a Data Passport that lists every model or service that read the text, and whether it was redacted first.",
  },
  {
    id: "faq-evidence",
    q: "What if there is no evidence?",
    a: "The line is marked unverified, never false. A reviewer decides whether to add a source, soften the claim or remove it.",
  },
  {
    id: "faq-confidential",
    q: "How are confidential files handled?",
    a: "Sources marked confidential are read by a local model only. They are never sent to an external service.",
  },
  {
    id: "faq-legal",
    q: "Is this legal advice?",
    a: "No. Regulation packs are guidance that helps reviewers spot risk. Your legal or compliance team makes the final call.",
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
