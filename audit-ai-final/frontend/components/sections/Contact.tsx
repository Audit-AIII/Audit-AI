import { Button } from "@/components/primitives/Button";
import { TextLink } from "@/components/primitives/TextLink";
import { Shore, type ShellSpot } from "@/components/layout/Shore";

/** Closing call to action: the landing page hands off to sign-in, where the review workflow lives. */
// Beach decor in the open sand right of the heading (hidden below 900px).
const SHELLS: ShellSpot[] = [
  { kind: "scallop", x: "78%", y: "150px", size: 120, rotate: 20 },
  { kind: "dollar", x: "88%", y: "330px", size: 64, rotate: -10 },
  { kind: "auger", x: "72%", y: "360px", size: 74, rotate: -48 },
  { kind: "pebble", x: "90%", y: "190px", size: 22 },
  { kind: "tide", x: "56%", y: "30px", size: 480 },
  { kind: "conch", x: "92%", y: "230px", size: 64, rotate: -24 },
  { kind: "pearls", x: "82%", y: "300px", size: 45 },
  { kind: "glass", x: "95%", y: "120px", size: 30, rotate: 40, tone: "slate" },
  { kind: "pebble", x: "70%", y: "250px", size: 27, tone: "terracotta" },
  { kind: "pebble", x: "86%", y: "440px", size: 30, rotate: 30, tone: "sage" },
];

export function Contact() {
  return (
    <section id="contact" className="section contact" aria-labelledby="contact-title">
      <Shore shells={SHELLS} />
      <div className="container">
        <h2 id="contact-title" className="contact__title">
          <span className="contact__line contact__line--raised sand-edge" data-r="up">
            <span className="hero__channel ply">
              <span className="contact__word relief-raised">Check</span>
            </span>
          </span>{" "}
          <span className="contact__line" data-r="up">
            <span className="contact__word relief-pressed grain-text" data-text="something.">
              something.
            </span>
          </span>
        </h2>

        <div className="contact__body">
          <div className="contact__cta" data-r="up">
            <p className="t-lead">
              Sign in to upload a draft, run the six checks and see every problem with the reason behind it.
            </p>
            <div className="hero__actions">
              <Button href="/login">Start a review</Button>
              <TextLink href="/login?mode=signup" arrow>
                Create an account
              </TextLink>
            </div>
          </div>

          <dl className="contact__aside">
            <div>
              <dt className="t-caption">Sample</dt>
              <dd>
                <TextLink href="#findings">See an example</TextLink>
              </dd>
            </div>
            <div>
              <dt className="t-caption">Your data</dt>
              <dd>
                <TextLink href="#faq-data">Where your data goes</TextLink>
              </dd>
            </div>
            <div>
              <dt className="t-caption">Disclosure</dt>
              <dd>
                <TextLink href="#ai-services">AI &amp; services</TextLink>
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </section>
  );
}
