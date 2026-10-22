import { TextLink } from "@/components/primitives/TextLink";

const PRODUCT = [
  { href: "/#checks", label: "Checks" },
  { href: "/#process", label: "Process" },
  { href: "/#findings", label: "Findings" },
  { href: "/#sources", label: "Sources" },
];
const TRUST = [
  { href: "#faq-data", label: "Data Passport" },
  { href: "#ai-services", label: "AI & services" },
  { href: "#faq-legal", label: "Limitations" },
];

/** Footer tray: raised wordmark on a dark inset panel, link columns, AI & services disclosure. */
export function Footer() {
  return (
    <footer className="footer">
      <div className="footer__tray">
        <p className="footer__mark relief-raised" aria-hidden="true">
          Audit AI.
        </p>
        <hr className="footer__rule" />
        <div className="footer__cols">
          <div className="footer__col">
            <h2 className="t-caption">Audit AI</h2>
            <p className="t-body">Brand governance that checks content before it is published.</p>
          </div>
          <nav className="footer__col" aria-label="Product">
            <h2 className="t-caption">Product</h2>
            <ul>
              {PRODUCT.map((l) => (
                <li key={l.href}>
                  <TextLink href={l.href}>{l.label}</TextLink>
                </li>
              ))}
            </ul>
          </nav>
          <nav className="footer__col" aria-label="Trust">
            <h2 className="t-caption">Trust</h2>
            <ul>
              {TRUST.map((l) => (
                <li key={l.href}>
                  <TextLink href={l.href}>{l.label}</TextLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className="footer__col">
            <h2 className="t-caption">Team</h2>
            <p className="t-body">Team CodeNinjas · Inkloom AI hackathon</p>
          </div>
        </div>

        <section id="ai-services" className="footer__disclosure" aria-labelledby="ai-services-title">
          <h2 id="ai-services-title" className="t-caption">
            AI &amp; services
          </h2>
          <p className="t-body">
            Audit AI uses AI models to propose findings and suggestions, and people make every decision. Each
            review&rsquo;s Data Passport lists the models and services involved. This site&rsquo;s frontend code was
            generated with Claude Code and reviewed by the team. Its visual system is modelled on the public style of
            relevovinco.com, re-implemented from scratch, with no code, copy or images copied.
          </p>
        </section>

        <div className="footer__base">
          <p className="t-body">© 2026 Audit AI · Team CodeNinjas</p>
          <TextLink href="#top">Back to the top</TextLink>
        </div>
      </div>
    </footer>
  );
}
