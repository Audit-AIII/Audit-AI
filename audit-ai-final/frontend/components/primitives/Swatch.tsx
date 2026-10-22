export type CheckKind = "tone" | "terminology" | "facts" | "claims" | "visual" | "accessibility";

/**
 * One of the six finishes, used as the visual for one of the six checks (DESIGN.md §0.1):
 * tone = burnish, terminology = texture plate, facts = die-cut window,
 * claims = blind emboss, visual = score & fold, accessibility = deboss.
 */
export function Swatch({ kind, className }: { kind: CheckKind; className?: string }) {
  return (
    <div className={`swatch swatch--${kind}${className ? ` ${className}` : ""}`} aria-hidden="true">
      <span className="swatch__mark" />
    </div>
  );
}
