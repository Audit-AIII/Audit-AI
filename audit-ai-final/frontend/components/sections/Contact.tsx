"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/primitives/Button";
import { Field, Textarea } from "@/components/primitives/Field";
import { TextLink } from "@/components/primitives/TextLink";

/** Contact: label-box title + pressed-well form. No backend yet, so submitting only confirms locally. */
export function Contact() {
  const [sent, setSent] = useState(false);

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (e.currentTarget.reportValidity()) setSent(true);
  };

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
          <form className="contact__form" onSubmit={onSubmit}>
            <Field label="Your name" id="c-name" name="name" autoComplete="name" required />
            <Field label="Email" id="c-email" name="email" type="email" autoComplete="email" required />
            <Textarea label="What are you publishing?" id="c-what" name="what" className="contact__wide" required />
            <div className="contact__submit">
              <Button type="submit">Start a review</Button>
              <p className="t-body contact__status" role="status" aria-live="polite">
                {sent ? "Thanks. This demo form does not send anything yet." : ""}
              </p>
            </div>
          </form>

          <dl className="contact__aside">
            <div>
              <dt className="t-caption">Sample</dt>
              <dd>
                <TextLink href="#findings">See a sample finding</TextLink>
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
