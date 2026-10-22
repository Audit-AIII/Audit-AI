export type CheckKind = "tone" | "terminology" | "facts" | "claims" | "visual" | "accessibility";

/**
 * Visual for one check, drawn in the pressed-paper language (raised = fine, pressed = flagged,
 * dark window = evidence, dashed = unverified). Decorative: the card's heading and text carry the meaning.
 */
function Visual({ kind }: { kind: CheckKind }) {
  switch (kind) {
    case "tone":
      // A voice dial: the draft's knob sits off the brand's range.
      return (
        <div className="sv sv--tone">
          <div className="sv-tone__scale">
            <span>Formal</span>
            <span>Playful</span>
          </div>
          <div className="sv-tone__track">
            <span className="sv-tone__range" />
            <span className="sv-tone__knob" />
          </div>
          <span className="sv-tag sv-tag--bad">Off-voice</span>
        </div>
      );
    case "terminology":
      // Approved terms raised; the misspelt one pressed in with its correction.
      return (
        <div className="sv sv--terms">
          <span className="sv-chip">Audit AI</span>
          <span className="sv-chip sv-chip--bad">
            <s>e-mail</s>
          </span>
          <span className="sv-chip">sign in</span>
          <span className="sv-chip sv-chip--fix">email</span>
        </div>
      );
    case "facts":
      // Evidence window: the approved value beside the drafted one.
      return (
        <div className="sv sv--facts">
          <div className="sv-window">
            <span className="sv-window__label">Fact sheet v3</span>
            <span className="sv-window__row">
              <span>Approved</span>
              <b>12 h</b>
            </span>
            <span className="sv-window__row sv-window__row--bad">
              <span>Draft</span>
              <b>24 h</b>
            </span>
          </div>
        </div>
      );
    case "claims":
      // A raised claim with no proof attached: the evidence slot is dashed (unverified).
      return (
        <div className="sv sv--claims">
          <span className="sv-claim">“No. 1 eco-friendly”</span>
          <span className="sv-slot">? Evidence</span>
        </div>
      );
    case "visual":
      // Approved palette raised; an off-palette colour pressed out of line.
      return (
        <div className="sv sv--visual">
          <span className="sv-dot" style={{ background: "var(--canvas)" }} />
          <span className="sv-dot" style={{ background: "var(--ink-2)" }} />
          <span className="sv-dot" style={{ background: "var(--surface)" }} />
          <span className="sv-dot sv-dot--bad" />
        </div>
      );
    case "accessibility":
      // Contrast check: sample text in a pressed ring with its ratio.
      return (
        <div className="sv sv--a11y">
          <span className="sv-ring">
            <b>Aa</b>
            <span>4.8 : 1</span>
          </span>
          <span className="sv-tag">AA pass</span>
        </div>
      );
  }
}

export function Swatch({ kind, className }: { kind: CheckKind; className?: string }) {
  return (
    <div className={`swatch swatch--${kind}${className ? ` ${className}` : ""}`} aria-hidden="true">
      <Visual kind={kind} />
    </div>
  );
}
