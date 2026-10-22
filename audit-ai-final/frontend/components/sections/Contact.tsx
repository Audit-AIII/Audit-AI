import { Button } from "@/components/primitives/Button";
import { TextLink } from "@/components/primitives/TextLink";

/** Closing call to action: the landing page hands off to sign-in, where the review workflow lives. */
export function Contact() {
  return (
    <section id="contact" className="section contact" aria-labelledby="contact-title">
      <div className="container">
        <h2 id="contact-title" className="contact__title">
          <span className="contact__line contact__line--raised" data-r="up">
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
