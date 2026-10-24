"use client";

/**
 * "The AI is working" state: a small paper sheet whose lines are pressed in, one by one, by the
 * landing page's roller (statement band) sweeping down it, plus the words of what is happening.
 * Reduced motion: no roller, lines stay pressed, the words carry it.
 * `announce` off when the page already has its own aria-live text for the same thing.
 */
export function Thinking({ label, detail, announce = true }: { label: string; detail?: string; announce?: boolean }) {
  return (
    <div className="thinking" {...(announce ? { role: "status", "aria-live": "polite" as const } : {})}>
      <span className="thinking__sheet" aria-hidden="true">
        <span className="thinking__line" />
        <span className="thinking__line" />
        <span className="thinking__line" />
        <span className="thinking__roller" />
      </span>
      <span className="thinking__text">
        <span className="thinking__label">
          {label}
          <span className="thinking__dots" aria-hidden="true">
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </span>
        </span>
        {detail && <span className="thinking__detail">{detail}</span>}
      </span>
    </div>
  );
}
